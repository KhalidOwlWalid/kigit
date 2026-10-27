#include "board.hpp"
#include "helpers.hpp"

#include <doctest/doctest.h>

#include <algorithm>
#include <cmath>

using namespace kigit;
using namespace kigit::test;

namespace {

const Item* find_id(const Board& b, const std::string& id) {
    for (const auto& it : b.items)
        if (it.id == id) return &it;
    return nullptr;
}

} // namespace

TEST_SUITE("board") {

TEST_CASE("demo board: items, layers and outline") {
    Board b = load_board(read_text(fixture("v1/demo.kicad_pcb")));
    REQUIRE(b.layers.size() == 2);
    CHECK(b.layers[0].name == "F.Cu");
    CHECK(b.layers[1].name == "B.Cu");
    CHECK(b.outline.size() == 1); // the gr_rect
    auto count = [&](ItemKind k) {
        return std::count_if(b.items.begin(), b.items.end(), [&](const Item& i) { return i.kind == k; });
    };
    CHECK(count(ItemKind::Pad) == 4);
    CHECK(count(ItemKind::Track) == 4);
    CHECK(count(ItemKind::Via) == 1);
}

TEST_CASE("pads are placed with their footprint's position and rotation") {
    // R2 sits at (20, 10) rotated 90 degrees; its pads are at (-1, 0) and (1, 0).
    Board b = load_board(read_text(fixture("v1/demo.kicad_pcb")));
    const Item* p1 = find_id(b, "fp-r2/1");
    const Item* p2 = find_id(b, "fp-r2/2");
    REQUIRE(p1);
    REQUIRE(p2);
    CHECK(p1->a.x == doctest::Approx(20));
    CHECK(p1->a.y == doctest::Approx(11));
    CHECK(p2->a.x == doctest::Approx(20));
    CHECK(p2->a.y == doctest::Approx(9));
    CHECK(p1->net == "SIG");
    CHECK(p1->ref == "R2");
}

TEST_CASE("items carry KiCad's ID: uuid (KiCad 8+) or tstamp (KiCad 6/7)") {
    Board b = load_board(read_text(fixture("v1/demo.kicad_pcb")));
    REQUIRE(find_id(b, "seg-1"));
    CHECK(find_id(b, "seg-1")->net == "SIG");
    CHECK(find_id(b, "via-1")->kind == ItemKind::Via);

    Board old = load_board(R"((kicad_pcb (version 20221018) (layers (0 "F.Cu" signal))
        (segment (start 0 0) (end 1 0) (width 0.2) (layer "F.Cu") (net 0) (tstamp "abc"))))");
    REQUIRE(old.items.size() == 1);
    CHECK(old.items[0].id == "abc");
}

TEST_CASE("old files: numbered nets resolve through the net table") {
    Board b = load_board(R"((kicad_pcb (version 20211014) (layers (0 "F.Cu" signal))
        (net 0 "") (net 1 "GND")
        (segment (start 0 0) (end 1 0) (width 0.2) (layer "F.Cu") (net 1))))");
    REQUIRE(b.items.size() == 1);
    CHECK(b.items[0].net == "GND");
}

TEST_CASE("a via exists on every copper layer it spans") {
    Board b = load_board(R"((kicad_pcb (version 20260206)
        (layers (0 "F.Cu" signal) (4 "In1.Cu" power "GND") (6 "In2.Cu" signal) (2 "B.Cu" signal))
        (via (at 1 1) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net "X"))))");
    REQUIRE(b.items.size() == 1);
    CHECK(b.items[0].layers == std::vector<std::string>{"F.Cu", "In1.Cu", "In2.Cu", "B.Cu"});
    CHECK(b.layers[1].display == "GND"); // user layer name
}

TEST_CASE("track identity ignores direction; arcs have their real length") {
    Item a, b;
    a.kind = b.kind = ItemKind::Track;
    a.net = b.net = "N";
    a.layers = b.layers = {"F.Cu"};
    a.width = b.width = 0.2;
    a.a = {0, 0};
    a.b = {3, 4};
    b.a = {3, 4};
    b.b = {0, 0};
    CHECK(a.key() == b.key());
    CHECK(a.length() == doctest::Approx(5));

    Item arc;
    arc.kind = ItemKind::Arc;
    arc.a = {0, 0};
    arc.mid = {1, 1};
    arc.b = {2, 0};
    CHECK(arc.length() == doctest::Approx(M_PI)); // half circle, radius 1
}

TEST_CASE("KiCad 5: arcs given as centre + angle") {
    // Corner arc: centre (10, 10), starting at (10, 10.4), sweeping -90 degrees,
    // must end at (10.4, 10), like KiCad draws it.
    Board b = load_board(R"((kicad_pcb (version 20171130) (layers (0 F.Cu signal) (44 Edge.Cuts user))
        (gr_arc (start 10 10) (end 10 10.4) (angle -90) (layer Edge.Cuts) (width 0.05))))");
    REQUIRE(b.outline.size() == 1);
    const std::string& d = b.outline[0];
    CHECK(d.rfind("M10 10.4", 0) == 0);
    CHECK(d.size() >= 7);
    CHECK(d.substr(d.size() - 7) == "10.4 10");
}

TEST_CASE("KiCad 5: zones take their layer from the zone itself") {
    Board b = load_board(R"((kicad_pcb (version 20171130) (layers (0 F.Cu signal))
        (net 0 "") (net 1 GND)
        (zone (net 1) (net_name GND) (layer F.Cu)
          (filled_polygon (pts (xy 0 0) (xy 5 0) (xy 5 5) (xy 0 5))))))");
    REQUIRE(b.items.size() == 1);
    CHECK(b.items[0].kind == ItemKind::Zone);
    CHECK(b.items[0].net == "GND");
    CHECK(b.items[0].layers == std::vector<std::string>{"F.Cu"});
    CHECK(b.items[0].polygons.size() == 1);
}

TEST_CASE("not a board") {
    CHECK_THROWS(load_board("(kicad_sch (version 1))"));
}

}
