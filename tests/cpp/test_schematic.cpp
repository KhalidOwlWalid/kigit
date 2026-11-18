#include "helpers.hpp"
#include "sch/schematic.hpp"

#include <doctest/doctest.h>

#include <map>
#include <optional>
#include <set>
#include <string>
#include <tuple>
#include <vector>

using namespace kigit;
using namespace kigit::test;

namespace {

using NetMap = std::map<std::string, std::set<std::string>>; // net name -> {"R1.2", ...}

// Nets with at least one part pin, the way KiCad's netlist lists them.
NetMap nets_of(const Schematic& s) {
    NetMap out;
    for (const auto& n : s.nets) {
        if (n.nodes.empty()) continue;
        auto& pins = out[n.name];
        for (const auto& node : n.nodes)
            pins.insert(s.symbols[node.symbol].ref + "." + s.symbols[node.symbol].pins[node.pin].number);
    }
    return out;
}

// The demo schematic, reading v1 or v2 plus the shared .kicad_pro.
Schematic demo(int version) {
    FileReader dir = folder_reader(fixture("v" + std::to_string(version)));
    FileReader pro = folder_reader(fixture(""));
    return load_schematic("demo.kicad_sch", [=](const std::string& rel) {
        return rel.ends_with(".kicad_pro") ? pro(rel) : dir(rel);
    });
}

const SchSymbol& symbol(const Schematic& s, const std::string& ref) {
    for (const auto& sym : s.symbols)
        if (sym.ref == ref) return sym;
    FAIL("no symbol " << ref);
    throw;
}

} // namespace

TEST_SUITE("schematic") {

// Expected values below are KiCad's own netlist (kicad-cli sch export
// netlist) for the fixture files.

TEST_CASE("demo v1: same nets and names as KiCad") {
    NetMap expected = {
        {"/SIG", {"R1.2", "R2.1"}},
        {"GND", {"R2.2"}},
        {"Net-(U1-IN)", {"R4.2", "U1.1"}},
        {"VCC", {"R1.1"}},
        {"VDD", {"U1.4"}},
        {"unconnected-(R3-Pad1)", {"R3.1"}},
        {"unconnected-(R3-Pad2)", {"R3.2"}},
        {"unconnected-(R4-Pad1)", {"R4.1"}},
        {"unconnected-(U1-A{slash}B-Pad3)", {"U1.3"}},
        {"unconnected-(U1-Pad2)", {"U1.2"}},
    };
    CHECK(nets_of(demo(1)) == expected);
}

TEST_CASE("demo v2: same nets and names as KiCad") {
    NetMap expected = {
        {"/SIG", {"C1.1", "R1.2", "R2.1"}},
        {"GND", {"C1.2", "R2.2"}},
        {"Net-(U1-IN)", {"R5.2", "U1.1"}},
        {"VCC", {"R1.1"}},
        {"VDD", {"U1.4"}},
        {"unconnected-(R3-Pad1)", {"R3.1"}},
        {"unconnected-(R3-Pad2)", {"R3.2"}},
        {"unconnected-(R5-Pad1)", {"R5.1"}},
        {"unconnected-(U1-A{slash}B-Pad3)", {"U1.3"}},
        {"unconnected-(U1-Pad2)", {"U1.2"}},
    };
    CHECK(nets_of(demo(2)) == expected);
}

TEST_CASE("pins are placed with the symbol's rotation") {
    Schematic s = demo(1);
    const SchSymbol& r2 = symbol(s, "R2"); // at (70, 50), rotated 90
    REQUIRE(r2.pins.size() == 2);
    CHECK(r2.pins[0].pos.x == doctest::Approx(66.19));
    CHECK(r2.pins[0].pos.y == doctest::Approx(50));
    CHECK(r2.pins[1].pos.x == doctest::Approx(73.81));
}

TEST_CASE("wires that merely cross don't connect") {
    // The wire (55,55)-(55,65) crosses the SIG wire at (55,60) with no junction.
    Schematic s = demo(1);
    int sig = -1, crossing = -1;
    for (size_t i = 0; i < s.nets.size(); ++i)
        if (s.nets[i].name == "/SIG") sig = static_cast<int>(i);
    for (const auto& w : s.wires)
        if (w.a.x == doctest::Approx(55) && w.a.y == doctest::Approx(55)) crossing = w.net;
    REQUIRE(sig >= 0);
    REQUIRE(crossing >= 0);
    CHECK(crossing != sig);
    CHECK(s.nets[crossing].nodes.empty());
}

TEST_CASE("a label touching a wire mid-way joins it") {
    Schematic s = demo(1);
    for (const auto& l : s.labels)
        if (l.text == "SIG") CHECK(s.nets[l.net].name == "/SIG");
}

TEST_CASE("PWR_FLAGs on different nets don't join them") {
    // Covered by the expected maps (VCC and GND stay apart); check directly too.
    Schematic s = demo(1);
    NetMap n = nets_of(s);
    CHECK(n.count("VCC") == 1);
    CHECK(n.count("GND") == 1);
    CHECK(n.count("PWR_FLAG") == 0);
}

TEST_CASE("hierarchy and two top-level sheets: same as KiCad") {
    Schematic s = load_schematic("hier.kicad_sch", folder_reader(fixture("hier")));
    NetMap expected = {
        {"/extra/Y", {"R3.1"}},
        {"/hier/Child/X", {"R1.2", "R2.1"}},
        {"GND", {"R1.1", "R2.2"}},
        {"unconnected-(R3-Pad2)", {"R3.2"}},
    };
    CHECK(nets_of(s) == expected);
    CHECK(s.sheets.size() == 3); // hier, its Child, extra
    CHECK(s.warnings.empty());
}

// The hier fixture with text changed on the way in: (file, from, to).
FileReader edited_hier(std::vector<std::tuple<std::string, std::string, std::string>> edits) {
    FileReader dir = folder_reader(fixture("hier"));
    return [=](const std::string& rel) -> std::optional<std::string> {
        auto text = dir(rel);
        if (!text) return text;
        for (const auto& [file, from, to] : edits) {
            if (file != rel) continue;
            auto at = text->find(from);
            REQUIRE(at != std::string::npos);
            text->replace(at, from.size(), to);
        }
        return text;
    };
}

std::string resistor(const std::string& ref, int x, int y, int rot, const std::string& path) {
    return "(symbol (lib_id \"Device:R\") (at " + std::to_string(x) + " " + std::to_string(y) + " " +
           std::to_string(rot) + ") (unit 1) (uuid \"u-" + ref + "\")\n" + "(property \"Reference\" \"" + ref +
           "\" (at 0 0 0)) (property \"Value\" \"1k\" (at 0 0 0))\n" + "(instances (project \"hier\" (path \"" +
           path + "\" (reference \"" + ref + "\") (unit 1)))))\n";
}

TEST_CASE("KiCad 6 sheet properties, and a / in a sheet name: same as KiCad") {
    // KiCad 6 wrote "Sheet name" / "Sheet file" (HackRF One's schematic did);
    // KiCad writes a "/" in a sheet name as {slash} in net names.
    Schematic s = load_schematic("hier.kicad_sch", edited_hier({
        {"hier.kicad_sch", "\"Sheetname\" \"Child\"", "\"Sheet name\" \"A/B\""},
        {"hier.kicad_sch", "\"Sheetfile\"", "\"Sheet file\""},
    }));
    NetMap expected = {
        {"/extra/Y", {"R3.1"}},
        {"/hier/A{slash}B/X", {"R1.2", "R2.1"}},
        {"GND", {"R1.1", "R2.2"}},
        {"unconnected-(R3-Pad2)", {"R3.2"}},
    };
    CHECK(nets_of(s) == expected);
    CHECK(s.warnings.empty());
}

TEST_CASE("a local label joins a global label of the same name on its sheet only: same as KiCad") {
    // Root: R13 has local "A" on one pin and global "A" on the other (one net).
    // Child: R14 has local "B"; root: R15 has global "B" (two nets).
    std::string root = resistor("R13", 120, 50, 0, "/hier-root") +
                       "(wire (pts (xy 120 46.19) (xy 120 40)) (uuid \"t-w1\"))\n"
                       "(label \"A\" (at 120 40 0))\n"
                       "(wire (pts (xy 120 53.81) (xy 120 60)) (uuid \"t-w2\"))\n"
                       "(global_label \"A\" (shape input) (at 120 60 270))\n" +
                       resistor("R15", 150, 50, 0, "/hier-root") +
                       "(wire (pts (xy 150 46.19) (xy 150 40)) (uuid \"t-w3\"))\n"
                       "(global_label \"B\" (shape input) (at 150 40 90))\n";
    std::string child = resistor("R14", 60, 80, 90, "/hier-root/sheet-child") +
                        "(wire (pts (xy 63.81 80) (xy 70 80)) (uuid \"t-w4\"))\n"
                        "(label \"B\" (at 70 80 0))\n";
    Schematic s = load_schematic("hier.kicad_sch", edited_hier({
        {"hier.kicad_sch", "(instances (project \"hier\" (path \"/hier-root\" (page \"2\"))))\n\t)",
         "(instances (project \"hier\" (path \"/hier-root\" (page \"2\"))))\n\t)\n" + root},
        {"child.kicad_sch", "(instances (project \"hier\" (path \"/hier-root/sheet-child\" (reference \"#PWR02\") (unit 1))))\n\t)",
         "(instances (project \"hier\" (path \"/hier-root/sheet-child\" (reference \"#PWR02\") (unit 1))))\n\t)\n" + child},
    }));
    NetMap expected = {
        {"/extra/Y", {"R3.1"}},
        {"/hier/Child/B", {"R14.2"}},
        {"/hier/Child/X", {"R1.2", "R2.1"}},
        {"A", {"R13.1", "R13.2"}},
        {"B", {"R15.1"}},
        {"GND", {"R1.1", "R2.2"}},
        {"unconnected-(R3-Pad2)", {"R3.2"}},
        {"unconnected-(R14-Pad1)", {"R14.1"}},
        {"unconnected-(R15-Pad2)", {"R15.2"}},
    };
    CHECK(nets_of(s) == expected);
}

TEST_CASE("buses across the hierarchy: same as KiCad") {
    // MAIN{GRP} (alias GRP = SIG AUX) on the parent feeds sheet pin B{GRP};
    // D[0..1] feeds Q[0..1]. Members pair by name (groups) or position (vectors).
    Schematic s = load_schematic("bus.kicad_sch", folder_reader(fixture("bus")));
    NetMap expected = {
        {"/D0", {"R11.1", "R3.1"}},
        {"/D1", {"R12.1", "R4.1"}},
        {"/MAIN.SIG", {"R1.1", "R10.1"}},
        {"unconnected-(R1-Pad2)", {"R1.2"}},
        {"unconnected-(R3-Pad2)", {"R3.2"}},
        {"unconnected-(R4-Pad2)", {"R4.2"}},
        {"unconnected-(R10-Pad2)", {"R10.2"}},
        {"unconnected-(R11-Pad2)", {"R11.2"}},
        {"unconnected-(R12-Pad2)", {"R12.2"}},
    };
    CHECK(nets_of(s) == expected);
    CHECK(s.warnings.empty());
    CHECK(s.buses.size() == 4);
    CHECK(s.bus_aliases.at("GRP") == std::vector<std::string>{"SIG", "AUX"});
    int bus_labels = 0;
    for (const auto& l : s.labels) bus_labels += l.bus;
    CHECK(bus_labels == 6); // 2 labels + 2 sheet pins + 2 hierarchical labels
}

TEST_CASE("buses are grouped, with their members' nets") {
    Schematic s = load_schematic("bus.kicad_sch", folder_reader(fixture("bus")));
    for (const auto& b : s.buses) {
        REQUIRE(b.group >= 0);
        CHECK(s.bus_groups[b.group].sheet == b.sheet);
    }
    for (const auto& l : s.labels)
        if (l.bus) CHECK(l.group >= 0);
    // Find the bus carrying MAIN{GRP} on the parent: members MAIN.SIG and MAIN.AUX.
    const SchBusGroup* main = nullptr;
    for (const auto& g : s.bus_groups)
        for (const auto& n : g.names)
            if (n == "MAIN{GRP}" && s.sheets[g.sheet].parent < 0) main = &g;
    REQUIRE(main != nullptr);
    std::map<std::string, std::string> members;
    for (const auto& [full, net] : main->members) members[full] = net >= 0 ? s.nets[net].name : "";
    REQUIRE(members.count("MAIN.SIG") == 1);
    CHECK(members["MAIN.SIG"] == "/MAIN.SIG");
    CHECK(members.count("MAIN.AUX") == 1);
}

TEST_CASE("missing sub-sheet file is a warning, not a failure") {
    FileReader dir = folder_reader(fixture("hier"));
    Schematic s = load_schematic("hier.kicad_sch", [&](const std::string& rel) -> std::optional<std::string> {
        if (rel == "child.kicad_sch") return std::nullopt;
        return dir(rel);
    });
    REQUIRE(s.warnings.size() == 1);
    CHECK(s.warnings[0].find("child.kicad_sch") != std::string::npos);
}

TEST_CASE("drawing data: fields, symbol shapes and pins") {
    Schematic s = demo(1);
    const SchSymbol& r1 = symbol(s, "R1");
    REQUIRE(s.defs.count(r1.def) == 1);
    const SymbolDef& def = s.defs.at(r1.def);
    CHECK(def.pins.size() == 2);
    CHECK(def.hide_numbers);
    CHECK(!def.graphics.empty());
    bool has_ref = false;
    for (const auto& f : r1.visible_fields) has_ref |= f.text == "R1";
    CHECK(has_ref);
}

}
