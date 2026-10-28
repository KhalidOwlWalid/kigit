// Source text for the viewer's source panel (--source): where items are in
// their files, and the snippets shown for them.
#include "helpers.hpp"
#include "pcb/board.hpp"
#include "report/source.hpp"
#include "sch/schematic.hpp"
#include "utils/sexpr.hpp"

#include <doctest/doctest.h>
#include <nlohmann/json.hpp>

using namespace kigit;
using namespace kigit::test;
using nlohmann::json;

namespace {

std::string_view text_of(std::string_view text, Span s) { return text.substr(s.begin, s.end - s.begin); }

json parse_ok(const RunResult& r) {
    INFO("stderr: " << r.err);
    REQUIRE(r.code == 0);
    return json::parse(r.out);
}

} // namespace

TEST_SUITE("source") {

TEST_CASE("lists know where they are in the text") {
    std::string text = "(a\n  (b 1)\n  (c \"x)\" 2))";
    sexpr::Node root = sexpr::parse(text);
    const sexpr::Node& a = root.children[0];
    CHECK(text_of(text, a.span) == text);
    CHECK(text_of(text, a.child("b")->span) == "(b 1)");
    CHECK(text_of(text, a.child("c")->span) == "(c \"x)\" 2)"); // a ")" inside quotes doesn't end it
}

TEST_CASE("snippets are whole lines with the first line's number") {
    std::string text = "line one\n\t(item\n\t\t(x 1)\n\t)\nlast";
    SourceFile f("demo.kicad_pcb", text);
    CHECK(f.line_of(0) == 1);
    CHECK(f.line_of(text.find("(item")) == 2);
    size_t b = text.find("(item"), e = text.find("\t)") + 2;
    json s = f.snippet({b, e});
    CHECK(s[0] == "demo.kicad_pcb");
    CHECK(s[1] == 2);
    CHECK(s[2] == "\t(item\n\t\t(x 1)\n\t)"); // indentation kept, no trailing newline
    CHECK(f.snippet({}).is_null());
}

TEST_CASE("a span cut before the next item stops at the line before it") {
    std::string text = "(zone\n\t(polygon 1)\n\t(filled_polygon 2)\n)";
    SourceFile f("b.kicad_pcb", text);
    json s = f.snippet({0, text.find("(filled_polygon")});
    CHECK(s[2] == "(zone\n\t(polygon 1)");
}

TEST_CASE("CRLF files show without the \\r") {
    std::string text = "(a\r\n\t(b 1)\r\n)\r\n";
    SourceFile f("w.kicad_sch", text);
    CHECK(f.snippet({0, text.rfind(')') + 1})[2] == "(a\n\t(b 1)\n)");
}

TEST_CASE("one entry per old/new pair") {
    std::string old_text = "(a 1)\n(b 2)", new_text = "(a 1)\n(b 3)";
    SourceFile o("f", old_text), n("f", new_text);
    SourceTable t;
    int first = t.add("b", &o, {6, 11}, &n, {6, 11});
    CHECK(t.add("b", &o, {6, 11}, &n, {6, 11}) == first); // the same pair again (e.g. its old position)
    CHECK(t.add("added", nullptr, {}, &n, {0, 5}) == first + 1);
    CHECK(t.add("nothing", nullptr, {}, nullptr, {}) == -1);
    const json& e = t.entries()[first];
    CHECK(e["o"][2] == "(b 2)");
    CHECK(e["n"][2] == "(b 3)");
    CHECK(t.entries()[first + 1]["o"].is_null());
}

TEST_CASE("board items, footprints and zones point at their text") {
    std::string text = read_text(fixture("v2/demo.kicad_pcb"));
    Board b = load_board(text);
    for (const Item& it : b.items) {
        if (it.kind == ItemKind::Zone) continue;
        std::string_view t = text_of(text, it.src);
        if (it.kind == ItemKind::Track) CHECK(t.starts_with("(segment"));
        if (it.kind == ItemKind::Via) CHECK(t.starts_with("(via"));
        if (it.kind == ItemKind::Pad) CHECK(t.starts_with("(pad"));
    }
    for (const Footprint& f : b.footprints) CHECK(text_of(text, f.src).starts_with("(footprint"));
    REQUIRE(!b.zones.empty());
    for (const ZoneInfo& z : b.zones) {
        CHECK(text_of(text, z.src).starts_with("(zone"));
        // Up to the fill: KiCad's computed polygons aren't part of it.
        CHECK(text_of(text, z.src).find("filled_polygon") == std::string_view::npos);
    }
}

TEST_CASE("schematic elements point at their text in their sheet's file") {
    Schematic s = load_schematic("hier.kicad_sch", folder_reader(fixture("hier")));
    CHECK(s.files.size() == 3); // hier, child, extra
    for (const auto& w : s.wires) {
        const std::string& text = s.files.at(s.sheets[w.sheet].file);
        CHECK(text_of(text, w.src).starts_with("(wire"));
    }
    for (const auto& l : s.labels) {
        const std::string& text = s.files.at(s.sheets[l.sheet].file);
        std::string_view t = text_of(text, l.src);
        CHECK((l.kind == LabelKind::SheetPin ? t.starts_with("(pin") : t.find("label") != std::string_view::npos));
    }
    for (const auto& sym : s.symbols) CHECK(text_of(s.files.at(s.sheets[sym.sheet].file), sym.src).starts_with("(symbol"));
}

TEST_CASE("--source is opt-in, and adds both files' text") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string board = quote((tmp / "board/demo.kicad_pcb").string());
    CHECK(!parse_ok(run_kigit("-n --json -o - -C " + board + " HEAD~3..HEAD")).contains("src"));
    json d = parse_ok(run_kigit("-n --json -o - --source -C " + board + " HEAD~3..HEAD"));
    REQUIRE(d["src"].is_array());
    REQUIRE(!d["src"].empty());
    bool both_sides = false;
    for (const auto& e : d["src"]) both_sides |= e["o"].is_array() && e["n"].is_array();
    CHECK(both_sides);
    // Items refer to entries.
    int with_src = 0;
    for (const auto& it : d["items"]) with_src += it.contains("src");
    CHECK(with_src > 0);

    // The viewer page also gets the schematic's entries.
    RunResult page = run_kigit("-n -o - --source -C " + board + " HEAD~3..HEAD");
    REQUIRE(page.code == 0);
    CHECK(page.out.find("demo.kicad_sch") != std::string::npos);
    CHECK(page.out.find("kigitSourcePanel") != std::string::npos);
}

}
