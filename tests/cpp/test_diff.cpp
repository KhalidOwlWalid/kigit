#include "diff.hpp"
#include "helpers.hpp"

#include <doctest/doctest.h>

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
    for (const auto& [net, s] : d.nets) CHECK_MESSAGE(!s.changed(), net);
}

TEST_CASE("v1 -> v2: moved, edited, added and unchanged items") {
    Board a = demo(1), b = demo(2);
    Diff d = diff_boards(a, b);

    // R2 moved 5 mm: its pads and the GND track that moved with it.
    CHECK(statuses(d, "fp-r2/1") == std::multiset{Status::Moved, Status::OldPosition});
    CHECK(statuses(d, "fp-r2/2") == std::multiset{Status::Moved, Status::OldPosition});
    CHECK(statuses(d, "seg-4") == std::multiset{Status::Moved, Status::OldPosition});
    CHECK(d.moved == 3);

    // Edited: an end dragged (seg-2), a new width (seg-3). Same ID, different copper.
    CHECK(statuses(d, "seg-2") == std::multiset{Status::Added, Status::Removed});
    CHECK(statuses(d, "seg-3") == std::multiset{Status::Added, Status::Removed});

    // New: a track and C1's pads. Untouched: the rest.
    CHECK(statuses(d, "seg-5") == std::multiset{Status::Added});
    CHECK(statuses(d, "fp-c1/1") == std::multiset{Status::Added});
    CHECK(statuses(d, "seg-1") == std::multiset{Status::Same});
    CHECK(statuses(d, "via-1") == std::multiset{Status::Same});
    CHECK(statuses(d, "fp-r1/1") == std::multiset{Status::Same});
}

TEST_CASE("v1 -> v2: per-net counts") {
    Diff d = diff_boards(demo(1), demo(2));
    const NetStats& sig = d.nets.at("SIG");
    CHECK(sig.added == 1);   // seg-2 (edited)
    CHECK(sig.removed == 1);
    CHECK(sig.moved == 1);   // R2 pad 1
    const NetStats& vcc = d.nets.at("VCC");
    CHECK(vcc.added == 2);   // seg-3 (edited) + seg-5 (new)
    CHECK(vcc.removed == 1);
    CHECK(vcc.pads_added == 1);
    CHECK(vcc.length_new > vcc.length_old);
    const NetStats& gnd = d.nets.at("GND");
    CHECK(gnd.moved == 2);   // seg-4 + R2 pad 2
    CHECK(gnd.pads_added == 1);
    CHECK(gnd.added == 0);
    CHECK(gnd.removed == 0);
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
    for (const auto& [net, s] : d.nets) CHECK_MESSAGE(!s.changed(), net);
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
    // ...and R2's pads show as removed + added.
    CHECK(d.nets.at("SIG").pads_added == 1);
    CHECK(d.nets.at("SIG").pads_removed == 1);
}

}
