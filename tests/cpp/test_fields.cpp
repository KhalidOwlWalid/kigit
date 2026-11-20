#include "helpers.hpp"
#include "sch/fields.hpp"

#include <doctest/doctest.h>

#include <string>

using namespace kigit;
using namespace kigit::test;

namespace {

Schematic load(const std::string& text) {
    return load_schematic("demo.kicad_sch", [&](const std::string& rel) -> std::optional<std::string> {
        if (rel == "demo.kicad_sch") return text;
        return std::nullopt;
    });
}

std::string field(const Schematic& s, const std::string& ref, const std::string& name) {
    for (const auto& sym : s.symbols)
        if (sym.ref == ref) {
            auto f = sym.fields.find(name);
            return f == sym.fields.end() ? "<none>" : f->second;
        }
    return "<no part>";
}

// KiCad 6 wrote numbered fields and a bare "hide".
const char* kKicad6 = R"((kicad_sch (version 20211123) (generator eeschema)
  (uuid root)
  (lib_symbols (symbol "Device:R" (symbol "R_1_1" (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1")))))
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (uuid "s1")
    (property "Reference" "R1" (id 0) (at 52 50 0))
    (property "Value" "1k" (id 1) (at 52 52 0))
    (property "Footprint" "R_0603" (id 2) (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Part Number" "OLD" (id 3) (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (pin "1" (uuid p1))
  )
)
)";

} // namespace

TEST_SUITE("fields") {

TEST_CASE("an existing field's value is replaced in place; nothing else moves") {
    std::string text = read_text(fixture("v2/demo.kicad_sch"));
    FieldsResult r = set_fields(text, {{"sym-r1", "Footprint", "x"}});  // refused: KiCad's own
    CHECK(r.changed == 0);
    REQUIRE(r.problems.size() == 1);
    CHECK(r.problems[0].find("KiCad's own fields") != std::string::npos);

    r = set_fields(text, {{"sym-r1", "MPN", "RC0603FR-0710KL"}, {"sym-r1", "Manufacturer", "Yageo"}});
    REQUIRE(r.problems.empty());
    CHECK(r.changed == 2);
    Schematic before = load(text), after = load(r.text);
    CHECK(field(after, "R1", "MPN") == "RC0603FR-0710KL");
    CHECK(field(after, "R1", "Manufacturer") == "Yageo");
    CHECK(field(after, "R2", "MPN") == "<none>");
    CHECK(same_design(before, after, {"MPN", "Manufacturer"}).empty());
    // Only lines were added, after R1's last field; everything else is as it was.
    size_t at = text.find("(property \"Footprint\" \"\" (at 50 50 0)");
    size_t end = text.find('\n', at);
    CHECK(r.text.substr(0, end) == text.substr(0, end));
    CHECK(r.text.substr(r.text.size() - (text.size() - end)) == text.substr(end));
    // New fields copy the hidden Footprint field's format.
    CHECK(r.text.find("\t\t(property \"MPN\" \"RC0603FR-0710KL\" (at 50 50 0) (effects (font (size 1.27 1.27)) (hide yes)))") !=
          std::string::npos);

    // Changing it again replaces the value only; the same value changes nothing.
    FieldsResult again = set_fields(r.text, {{"sym-r1", "MPN", "say \"hi\""}, {"sym-r1", "Manufacturer", "Yageo"}});
    CHECK(again.changed == 1);
    CHECK(again.text.size() == r.text.size() - std::string("RC0603FR-0710KL").size() + std::string("say \\\"hi\\\"").size());
    CHECK(field(load(again.text), "R1", "MPN") == "say \"hi\"");
}

TEST_CASE("KiCad 6 files: numbered fields, a bare hide") {
    FieldsResult r = set_fields(kKicad6, {{"s1", "Part Number", "NEW"}, {"s1", "MPN", "X1"}});
    REQUIRE(r.problems.empty());
    CHECK(r.changed == 2);
    CHECK(std::string(r.text).find("(property \"Part Number\" \"NEW\" (id 3)") != std::string::npos);
    CHECK(std::string(r.text).find("(property \"MPN\" \"X1\" (id 4) (at 50 50 0)\n      (effects (font (size 1.27 1.27)) hide)") !=
          std::string::npos);
    Schematic after = load(r.text);
    CHECK(field(after, "R1", "MPN") == "X1");
    CHECK(same_design(load(kKicad6), after, {"MPN", "Part Number"}).empty());
}

TEST_CASE("Windows line endings stay Windows line endings") {
    std::string text = read_text(fixture("v2/demo.kicad_sch")), crlf;
    for (char c : text) crlf += c == '\n' ? std::string("\r\n") : std::string(1, c);
    FieldsResult r = set_fields(crlf, {{"sym-r2", "MPN", "A"}});
    REQUIRE(r.changed == 1);
    size_t lf = 0;
    for (size_t i = 0; i < r.text.size(); ++i)
        if (r.text[i] == '\n' && (i == 0 || r.text[i - 1] != '\r')) ++lf;
    CHECK(lf == 0);
}

TEST_CASE("refused: KiCad's own fields, bad names and values, unknown symbols") {
    for (const char* name : {"Reference", "value", "Footprint", "Datasheet", "Description", "ki_keywords", "Sim.Pins",
                             "Sheetfile", ""})
        CHECK_MESSAGE(!field_refused(name).empty(), name);
    for (const char* name : {"MPN", "Manufacturer", "LCSC Part #", "DigiKey", "Tolerance"})
        CHECK_MESSAGE(field_refused(name).empty(), name);
    std::string text = read_text(fixture("v2/demo.kicad_sch"));
    FieldsResult r = set_fields(text, {{"nope", "MPN", "x"}, {"sym-r1", "MPN", "two\nlines"}});
    CHECK(r.changed == 0);
    CHECK(r.problems.size() == 2);
    CHECK(r.text == text);
    // Emptying a field that isn't there adds nothing.
    CHECK(set_fields(text, {{"sym-r1", "MPN", ""}}).text == text);
}

TEST_CASE("renaming a field: only its name changes, refused when it would clash") {
    std::string text = kKicad6;
    FieldsResult r = set_fields(text, {{"s1", "Part Number", "", "Voltage rating"}});
    REQUIRE(r.problems.empty());
    CHECK(r.changed == 1);
    std::string want = text;
    want.replace(want.find("\"Part Number\""), 13, "\"Voltage rating\"");
    CHECK(r.text == want); // the name, nothing else (value, id, position, hide)
    Schematic before = load(text), after = load(r.text);
    CHECK(field(after, "R1", "Voltage rating") == "OLD");
    CHECK(field(after, "R1", "Part Number") == "<none>");
    CHECK(same_design(before, after, {"Part Number", "Voltage rating"}).empty());
    CHECK_FALSE(same_design(before, after, {"Part Number"}).empty()); // the new name is a change too

    CHECK(set_fields(text, {{"s1", "Tolerance", "", "Tol"}}).changed == 0);     // no such field: nothing
    r = set_fields(text, {{"s1", "Part Number", "", "Value"}});                  // KiCad's own: refused
    CHECK(r.changed == 0);
    CHECK(r.problems[0].find("KiCad's own") != std::string::npos);
    r = set_fields(text, {{"s1", "Part Number", "", "Footprint2"}, {"s1", "Footprint2", "x"}});
    CHECK(r.changed == 0); // a rename to a name also being set: two fields of one name, so refused
    CHECK(r.problems[0].find("at once") != std::string::npos);
    std::string two = text;
    two.replace(two.find("(pin \"1\""), 0, "(property \"Tol\" \"1%\" (id 4) (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n    ");
    r = set_fields(two, {{"s1", "Part Number", "", "Tol"}});
    CHECK(r.changed == 0);
    REQUIRE(r.problems.size() == 1);
    CHECK(r.problems[0].find("already has both") != std::string::npos);
}

TEST_CASE("same_design notices any change to the design") {
    std::string text = read_text(fixture("v2/demo.kicad_sch"));
    Schematic a = load(text);
    auto edited = [&](const std::string& from, const std::string& to) {
        std::string t = text;
        t.replace(t.find(from), from.size(), to);
        return load(t);
    };
    CHECK(same_design(a, a, {}).empty());
    CHECK(!same_design(a, edited("\"Value\" \"1k\"", "\"Value\" \"2k\""), {"Value"}).empty()); // even if "edited"
    CHECK(!same_design(a, edited("\"Footprint\" \"\" (at 50", "\"Footprint\" \"R_0402\" (at 50"), {}).empty());
    CHECK(!same_design(a, edited("(xy 50 60) (xy 60 60)", "(xy 50 60) (xy 61 60)"), {}).empty()); // a wire moved
    std::string with = set_fields(text, {{"sym-r1", "MPN", "x"}}).text;
    CHECK(!same_design(a, load(with), {}).empty()); // a field not said to be edited
    CHECK(same_design(a, load(with), {"MPN"}).empty());
}

} // TEST_SUITE
