// Board model: the net-carrying copper items of a .kicad_pcb file.
#pragma once

#include <string>
#include <string_view>
#include <vector>

namespace kigit {

struct Point {
    double x = 0, y = 0;
};

struct Layer {
    std::string name;    // canonical name used by items, e.g. "In1.Cu"
    std::string display; // user name if set, e.g. "GND"
    bool copper = false;
};

enum class ItemKind { Track, Arc, Via, Pad, Zone };

struct Item {
    ItemKind kind = ItemKind::Track;
    std::string net;                 // net name, "" for no net
    std::vector<std::string> layers; // copper layers this item is on

    // Track: a -> b.  Arc: a -> mid -> b.  Via/Pad: a is the centre.
    Point a, b, mid;
    double width = 0;                // track/arc width, via diameter

    // Via / pad
    double drill = 0;

    // Pad
    Point size;
    double angle = 0;                // degrees, KiCad convention (CCW, y down)
    std::string shape;               // rect, roundrect, circle, oval, ...
    double rratio = 0;               // roundrect corner ratio
    std::string ref;                 // footprint reference, e.g. "R18"
    std::string pad_number;

    // KiCad's permanent ID for the item, kept when it's moved ("" if none).
    // Pads use their footprint's ID plus the pad number.
    std::string id;

    // Zone: filled polygons, each closed.
    std::vector<std::vector<Point>> polygons;

    // Copper length in mm (tracks and arcs only, 0 otherwise).
    double length() const;

    // Identity used to match items between two revisions: same kind,
    // net, layers and geometry (rounded to 1 nm).
    std::string key() const;
};

struct Board {
    std::vector<Layer> layers;       // copper layers in stackup order (F.Cu first)
    std::vector<Item> items;
    std::vector<std::string> outline; // Edge.Cuts shapes as SVG path data
    int version = 0;                  // file format version, e.g. 20260206
};

// Parses .kicad_pcb text. Throws std::runtime_error on bad input.
Board load_board(std::string_view text);

// Centre of the circle through three points (for arcs). Returns false if
// the points are collinear.
bool circle_center(Point a, Point m, Point b, Point& c);

// SVG helpers shared with the HTML writer.
std::string svg_arc_path(Point a, Point m, Point b); // "M.. A.." through 3 points
std::string svg_num(double v);                       // compact number, 4 decimals max

} // namespace kigit
