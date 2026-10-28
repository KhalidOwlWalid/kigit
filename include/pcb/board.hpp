// Board model: the net-carrying copper items of a .kicad_pcb file.
#pragma once

#include <map>
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

    // Pad, relative to its footprint: position and angle in the footprint's
    // own frame. Unchanged when the footprint is moved or rotated, changed
    // when the footprint itself is edited (e.g. a new pad pitch).
    Point local;
    double local_angle = 0;
    std::string fp_id;

    // Zone: filled polygons, each closed.
    std::vector<std::vector<Point>> polygons;

    // Copper length in mm (tracks and arcs only, 0 otherwise).
    double length() const;

    // Identity used to match items between two revisions: same kind,
    // net, layers and geometry (rounded to 1 nm).
    std::string key() const;
};

// A footprint as a whole, for spotting changes that aren't copper: its
// graphics (fab/courtyard/silkscreen lines and texts), its fields, and the
// shape of its pads relative to itself.
struct Footprint {
    std::string id, ref, lib;           // lib: library footprint, e.g. "Resistor_SMD:R_0402"
    std::string side;                   // "F.Cu" or "B.Cu"
    Point at;
    double angle = 0;
    std::map<std::string, std::string> fields; // Value, Description, ..., "3D model"
    std::vector<std::string> graphics;  // non-copper drawings, canonical form, footprint frame
    std::vector<std::string> pads;      // pad shapes and places, canonical form, footprint frame
};

// A copper pour, for telling a real edit (outline) from a refill.
struct ZoneInfo {
    std::string id, net, name;
    std::vector<std::string> layers;
    size_t outline = 0;                 // hash of the outline the user drew
    size_t fill = 0;                    // hash of KiCad's computed fill
};

// A silkscreen line/shape or text, in board coordinates.
struct SilkItem {
    bool front = true;               // F.SilkS (else B.SilkS)
    std::string d;                   // SVG path for shapes ("" for text)
    double width = 0;                // line width
    bool fill = false;               // filled polygon/circle/rect
    std::string text;                // text items
    Point at;
    double angle = 0, size = 1, thickness = 0.15;
    int h = 0, v = 0;                // justification: -1 left/top, 0 centre, 1 right/bottom
    bool mirror = false;             // back-side text reads mirrored from the top
    std::string owner;               // footprint ID ("" = drawn on the board itself)
    std::string key;                 // identity for diffing: owner + shape in the owner's frame
};

struct Board {
    std::vector<Layer> layers;       // copper layers in stackup order (F.Cu first)
    std::vector<Item> items;
    std::vector<Footprint> footprints;
    std::vector<ZoneInfo> zones;
    std::vector<SilkItem> silk;      // only filled in if asked for (load_board(..., true))
    std::vector<std::string> outline; // Edge.Cuts shapes as SVG path data
    int version = 0;                  // file format version, e.g. 20260206
};

// Parses .kicad_pcb text. Throws std::runtime_error on bad input.
// With `silkscreen`, also reads the silkscreen (costs time and page size,
// so it's opt-in).
Board load_board(std::string_view text, bool silkscreen = false);

// Centre of the circle through three points (for arcs). Returns false if
// the points are collinear.
bool circle_center(Point a, Point m, Point b, Point& c);

// SVG helpers shared with the HTML writer.
std::string svg_arc_path(Point a, Point m, Point b); // "M.. A.." through 3 points
std::string svg_num(double v);                       // compact number, 4 decimals max

} // namespace kigit
