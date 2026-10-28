#include "helpers.hpp"
#include "sch/sch_diff.hpp"

#include <doctest/doctest.h>

using namespace kigit;
using namespace kigit::test;

namespace {

Schematic demo(int version) {
    FileReader dir = folder_reader(fixture("v" + std::to_string(version)));
    FileReader pro = folder_reader(fixture(""));
    return load_schematic("demo.kicad_sch", [=](const std::string& rel) {
        return rel.ends_with(".kicad_pro") ? pro(rel) : dir(rel);
    });
}

const SymbolDiff& part(const SchDiff& d, const std::string& ref_after) {
    for (const auto& s : d.symbols)
        if (s.ref_after == ref_after || (s.ref_after.empty() && s.ref_before == ref_after)) return s;
    FAIL("no part " << ref_after);
    throw;
}

const NetDiff& net(const SchDiff& d, const std::string& name) {
    for (const auto& n : d.nets)
        if (n.name_after == name || (n.name_after.empty() && n.name_before == name)) return n;
    FAIL("no net " << name);
    throw;
}

std::vector<std::string> texts(const std::vector<PinRef>& pins) {
    std::vector<std::string> out;
    for (const auto& p : pins) out.push_back(p.text());
    return out;
}

} // namespace

TEST_SUITE("schematic diff") {

TEST_CASE("identical schematics: nothing changed") {
    Schematic a = demo(1), b = demo(1);
    SchDiff d = diff_schematics(a, b);
    for (const auto& s : d.symbols) CHECK_MESSAGE(s.status == SchStatus::Same, s.ref_after);
    for (const auto& n : d.nets) CHECK_MESSAGE(n.status == SchStatus::Same, n.name_after);
    for (auto st : d.wires_new) CHECK(st == SchStatus::Same);
}

TEST_CASE("v1 -> v2 parts") {
    Schematic a = demo(1), b = demo(2);
    SchDiff d = diff_schematics(a, b);

    CHECK(part(d, "C1").status == SchStatus::Added);

    const SymbolDiff& r2 = part(d, "R2"); // value 10k -> 4k7
    CHECK(r2.status == SchStatus::Changed);
    CHECK(r2.electrical());
    REQUIRE(r2.fields.size() == 1);
    CHECK(r2.fields[0].field == "Value");
    CHECK(r2.fields[0].before == "10k");
    CHECK(r2.fields[0].after == "4k7");

    const SymbolDiff& r3 = part(d, "R3"); // only moved
    CHECK(r3.status == SchStatus::Changed);
    CHECK(r3.moved);
    CHECK(!r3.electrical());
    CHECK(!r3.fields_only());

    const SymbolDiff& r5 = part(d, "R5"); // R4 re-annotated, matched by its ID
    CHECK(r5.ref_before == "R4");
    CHECK(r5.fields_only());
    CHECK(!r5.electrical());

    CHECK(part(d, "R1").status == SchStatus::Same);
    CHECK(part(d, "U1").status == SchStatus::Same);
}

TEST_CASE("v1 -> v2 nets") {
    Schematic a = demo(1), b = demo(2);
    SchDiff d = diff_schematics(a, b);

    const NetDiff& sig = net(d, "/SIG");
    CHECK(sig.status == SchStatus::Changed);
    CHECK(texts(sig.joined) == std::vector<std::string>{"C1.1"});
    CHECK(sig.left.empty());
    CHECK(sig.wires_added == 1);

    const NetDiff& gnd = net(d, "GND");
    CHECK(texts(gnd.joined) == std::vector<std::string>{"C1.2"});

    // R4 -> R5 renames its unconnected pin's generated net; same pin, so a
    // rename, not a new net.
    const NetDiff& r5 = net(d, "unconnected-(R5-Pad1)");
    CHECK(r5.status == SchStatus::Changed);
    CHECK(r5.name_before == "unconnected-(R4-Pad1)");
    CHECK(!r5.electrical());

    CHECK(net(d, "VCC").status == SchStatus::Same);
}

TEST_CASE("a net that disappears into another reports where it went") {
    // Copy of v1 with one extra wire from R3 pin 1 (90, 46.19) to the VCC
    // wire's end (50, 40): R3.1's own "unconnected" net merges into VCC.
    std::string v1 = read_text(fixture("v1/demo.kicad_sch"));
    std::string merged = v1.substr(0, v1.rfind(')')) +
                         "\t(wire (pts (xy 90 46.19) (xy 50 40)) (uuid \"w-extra\"))\n)\n";
    FileReader pro = folder_reader(fixture(""));
    auto reader = [&](const std::string& text) {
        return [=](const std::string& rel) -> std::optional<std::string> {
            return rel.ends_with(".kicad_pro") ? pro(rel) : std::optional<std::string>(text);
        };
    };
    Schematic a = load_schematic("demo.kicad_sch", reader(v1));
    Schematic b = load_schematic("demo.kicad_sch", reader(merged));
    SchDiff d = diff_schematics(a, b);

    const NetDiff& gone = net(d, "unconnected-(R3-Pad1)");
    CHECK(gone.status == SchStatus::Removed);
    CHECK(gone.merged_into == "VCC");
    CHECK(texts(net(d, "VCC").joined) == std::vector<std::string>{"R3.1"});
    CHECK(part(d, "R3").electrical()); // its pin changed net
}

}
