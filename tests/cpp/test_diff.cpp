#include "diff.hpp"
#include "helpers.hpp"

#include <doctest/doctest.h>

#include <array>
#include <map>
#include <set>

using namespace kigit;
using namespace kigit::test;

namespace {

Board demo(int version) {
    return load_board(read_text(fixture("v" + std::to_string(version) + "/demo.kicad_pcb")));
}

// Statuses an item ID ended up with (old and new side), e.g. {Removed, Added}.
std::multiset<Status> statuses(const Diff& d, const std::string& id) {
    std::multiset<Status> out;
    for (const auto& di : d.items)
        if (di.item->id == id) out.insert(di.status);
    return out;
}

int total(const Diff& d, Status st) {
    int n = 0;
    for (const auto& di : d.items) n += di.status == st;
    return n;
}

} // namespace

TEST_SUITE("pcb diff") {

TEST_CASE("identical boards: everything unchanged") {
    Board a = demo(1), b = demo(1);
    Diff d = diff_boards(a, b);
    CHECK(total(d, Status::Same) == 9);
    CHECK(total(d, Status::Added) == 0);
    CHECK(total(d, Status::Removed) == 0);
    CHECK(d.moved == 0);
    for (const auto& [net, s] : d.nets) CHECK_MESSAGE(!s.changed_any(), net);
}

TEST_CASE("v1 -> v2: moved, changed in place, added and unchanged items") {
    Board a = demo(1), b = demo(2);
    Diff d = diff_boards(a, b);

    // R2 moved 5 mm as a whole: its pads and the GND track that moved with it.
    CHECK(statuses(d, "fp-r2/1") == std::multiset{Status::Moved, Status::OldPosition});
    CHECK(statuses(d, "fp-r2/2") == std::multiset{Status::Moved, Status::OldPosition});
    CHECK(statuses(d, "seg-4") == std::multiset{Status::Moved, Status::OldPosition});
    CHECK(d.moved == 3);

    // Changed in place (same ID, different copper): an end dragged (seg-2),
    // a new width (seg-3), and R1's pads, which moved *within* R1 (new pitch).
    CHECK(statuses(d, "seg-2") == std::multiset{Status::Changed, Status::OldPosition});
    CHECK(statuses(d, "seg-3") == std::multiset{Status::Changed, Status::OldPosition});
    CHECK(statuses(d, "fp-r1/1") == std::multiset{Status::Changed, Status::OldPosition});
    CHECK(statuses(d, "fp-r1/2") == std::multiset{Status::Changed, Status::OldPosition});
    CHECK(d.changed == 4);

    // New: a track and C1's pads. Untouched: the rest.
    CHECK(statuses(d, "seg-5") == std::multiset{Status::Added});
    CHECK(statuses(d, "fp-c1/1") == std::multiset{Status::Added});
    CHECK(statuses(d, "seg-1") == std::multiset{Status::Same});
    CHECK(statuses(d, "via-1") == std::multiset{Status::Same});
}

TEST_CASE("v1 -> v2: per-net counts") {
    Diff d = diff_boards(demo(1), demo(2));
    const NetStats& sig = d.nets.at("SIG");
    CHECK(sig.added == 0);
    CHECK(sig.removed == 0);
    CHECK(sig.changed == 2); // seg-2 + R1 pad 2
    CHECK(sig.moved == 1);   // R2 pad 1
    const NetStats& vcc = d.nets.at("VCC");
    CHECK(vcc.added == 1);   // seg-5
    CHECK(vcc.removed == 0);
    CHECK(vcc.changed == 2); // seg-3 + R1 pad 1
    CHECK(vcc.pads_added == 1);
    CHECK(vcc.length_new > vcc.length_old);
    const NetStats& gnd = d.nets.at("GND");
    CHECK(gnd.moved == 2);   // seg-4 + R2 pad 2
    CHECK(gnd.pads_added == 1);
    CHECK(gnd.changed == 0);
    CHECK(gnd.changed_any()); // C1's pad was added
}

TEST_CASE("v1 -> v2: footprints") {
    Board a = demo(1), b = demo(2);
    Diff d = diff_boards(a, b);
    auto find = [&](const std::string& ref) -> const FootprintDiff* {
        for (const auto& f : d.footprints)
            if (f.ref() == ref) return &f;
        return nullptr;
    };
    // R1 updated from the library: new pad pitch, an extra silkscreen line, a Description.
    const FootprintDiff* r1 = find("R1");
    REQUIRE(r1);
    CHECK(r1->status == Status::Changed);
    CHECK(r1->pads_changed);
    CHECK(!r1->moved);
    CHECK(r1->graphics_added == 2); // the silkscreen line + the Description's text
    CHECK(r1->graphics_removed == 0);
    REQUIRE(r1->fields.size() == 1);
    CHECK(r1->fields[0] == std::array<std::string, 3>{"Description", "", "updated footprint"});

    // R2 only moved: nothing about the footprint itself changed.
    const FootprintDiff* r2 = find("R2");
    REQUIRE(r2);
    CHECK(r2->moved);
    CHECK(!r2->pads_changed);
    CHECK(!r2->graphics_changed());
    CHECK(r2->fields.empty());

    REQUIRE(find("C1"));
    CHECK(find("C1")->status == Status::Added);
    CHECK(d.footprints.size() == 3);
}

TEST_CASE("v1 -> v2: a refill is told apart from an edited outline") {
    Diff d = diff_boards(demo(1), demo(2));
    REQUIRE(d.zone_changes.size() == 2);
    for (const auto& z : d.zone_changes) {
        if (z.new_zone->net == "GND") CHECK(z.kind == ZoneDiff::Refilled);
        if (z.new_zone->net == "VCC") CHECK(z.kind == ZoneDiff::OutlineChanged);
    }
}

TEST_CASE("v1 -> v2: silkscreen") {
    std::string v1 = read_text(fixture("v1/demo.kicad_pcb")), v2 = read_text(fixture("v2/demo.kicad_pcb"));
    Board a = load_board(v1, true), b = load_board(v2, true);
    Diff d = diff_boards(a, b);
    std::map<std::string, std::multiset<Status>> by_owner;
    for (const auto& s : d.silk) by_owner[s.item->owner].insert(s.status);
    // R1: unchanged line + reference, one new line. R2 moved, so its silkscreen
    // moved with it. C1 is new: its line and reference are added.
    CHECK(by_owner["fp-r1"] == std::multiset{Status::Same, Status::Same, Status::Added});
    CHECK(by_owner["fp-r2"] == std::multiset{Status::Moved, Status::Moved});
    CHECK(by_owner["fp-c1"] == std::multiset{Status::Added, Status::Added});
    CHECK(diff_boards(demo(1), demo(2)).silk.empty()); // not loaded: not compared
}

TEST_CASE("rotating a footprint moves its pads; it doesn't change them") {
    // Same footprint at 0 and at 90 degrees: KiCad stores the pads' angles as
    // absolute, so they differ, but relative to the footprint nothing changed.
    auto board = [](int angle) {
        std::string a = std::to_string(angle);
        return load_board(R"((kicad_pcb (version 20260206) (layers (0 "F.Cu" signal))
            (footprint "Demo:R" (layer "F.Cu") (uuid "fp") (at 10 10 )" + a + R"()
              (property "Reference" "R1" (at 0 -1.5 )" + a + R"() (layer "F.SilkS"))
              (fp_line (start -0.5 -0.4) (end 0.5 -0.4) (layer "F.SilkS"))
              (pad "1" smd rect (at -1 0 )" + a + R"() (size 0.8 0.9) (layers "F.Cu") (net "A"))
              (pad "2" smd rect (at 1 0 )" + a + R"() (size 0.8 0.9) (layers "F.Cu") (net "B")))))");
    };
    Board a = board(0), b = board(90);
    Diff d = diff_boards(a, b);
    CHECK(d.moved == 2);
    CHECK(d.changed == 0);
    REQUIRE(d.footprints.size() == 1);
    CHECK(d.footprints[0].moved);
    CHECK(!d.footprints[0].pads_changed);
    CHECK(!d.footprints[0].graphics_changed());
}

TEST_CASE("moving the whole layout is all 'moved', not removed + added") {
    Board a = demo(1), b = demo(1);
    for (auto& it : b.items) {
        for (Point* p : {&it.a, &it.b, &it.mid}) {
            p->x += 97;
            p->y += 1;
        }
    }
    Diff d = diff_boards(a, b);
    CHECK(d.moved == 9);
    CHECK(total(d, Status::Added) == 0);
    CHECK(total(d, Status::Removed) == 0);
    for (const auto& [net, s] : d.nets) CHECK_MESSAGE(!s.changed_any(), net);
}

TEST_CASE("without IDs, matching falls back to geometry") {
    Board a = demo(1), b = demo(2);
    for (Board* bd : {&a, &b})
        for (auto& it : bd->items) it.id.clear();
    Diff d = diff_boards(a, b);
    CHECK(d.moved == 0); // can't tell a move without IDs
    // Unchanged copper still matches by position...
    int same = 0;
    for (const auto& di : d.items)
        if (di.status == Status::Same && di.item->kind == ItemKind::Track && di.item->net == "SIG") ++same;
    CHECK(same == 1); // seg-1
    // ...and the pads that moved (R2) or changed (R1) show as removed + added.
    CHECK(d.nets.at("SIG").pads_added == 2);
    CHECK(d.nets.at("SIG").pads_removed == 2);
    CHECK(d.changed == 0);
}

}
