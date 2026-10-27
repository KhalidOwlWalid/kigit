// Schematic model: sheets, symbols, wires and labels of a KiCad project,
// plus the nets they form.
//
// KiCad doesn't store nets in .kicad_sch files. A wire is just two points;
// what it connects to is worked out from what touches it. connect() does that,
// following KiCad's rules for labels, power symbols and sheet hierarchy.
#pragma once

#include "board.hpp" // Point

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace kigit {

// A piece of text as KiCad places it: anchor point, angle, size and
// justification (h: -1 left, 0 center, 1 right; v: -1 top, 0 center, 1 bottom).
struct SchText {
    std::string text;
    Point at;
    double angle = 0;
    double size = 1.27;
    int h = 0, v = 0;
    bool hidden = false;
};

// How a library symbol looks, for one unit and body style. Coordinates are
// relative to the symbol origin with y pointing down (already flipped from
// the library's y-up).
struct SymbolGraphic {
    std::string d; // SVG path data
    int fill = 0;  // 0 none, 1 filled with the outline colour, 2 body background
    double width = 0; // line width in mm, 0 = default
};

struct SymbolPinDraw {
    Point at;            // connection point
    double angle = 0;    // direction from the connection point into the body (degrees, CCW)
    double length = 2.54;
    std::string number, name;
    double number_size = 1.27, name_size = 1.27;
    bool hidden = false;
};

struct SymbolDef {
    std::vector<SymbolGraphic> graphics;
    std::vector<SymbolPinDraw> pins; // same order as SchSymbol::pins
    double name_offset = 0.508;      // > 0: pin names inside the body; 0: above the pin line
    bool hide_names = false, hide_numbers = false;
};

struct SheetInstance {
    std::string file;      // e.g. "GPIOs.kicad_sch", relative to the root's folder
    std::string name;      // sheet name, "" for the root
    std::string path;      // human path used in net names, e.g. "/owl_v1/GPIOs/"
    std::string uuid_path; // KiCad instance path, e.g. "/<root uuid>/<sheet uuid>"
    int parent = -1;       // index of the parent instance, -1 for the root
    Point paper{297, 210}; // page size in mm
};

struct SchPin {
    std::string number, name, type; // type: passive, input, power_in, ...
    Point pos;                       // absolute position on the sheet
    bool hidden = false;
    int net = -1;
};

struct SchSymbol {
    int sheet = 0;                   // SheetInstance index
    std::string uuid, lib_id, ref, value, footprint;
    std::map<std::string, std::string> fields; // other properties (MPN, Datasheet, ...)
    int unit = 1;
    Point at;
    double angle = 0;
    bool mirror_x = false, mirror_y = false;
    bool power = false;              // power symbol (GND, +3.3V, ...)
    std::vector<SchPin> pins;
    std::string def;                 // key into Schematic::defs (drawing)
    std::vector<SchText> visible_fields; // reference, value, ... as shown on the sheet
};

struct SchWire {
    int sheet = 0;
    Point a, b;
    int net = -1;
};

enum class LabelKind { Local, Global, Hierarchical, SheetPin };

struct SchLabel {
    int sheet = 0;                   // for SheetPin: the sheet the sheet symbol is drawn on
    LabelKind kind = LabelKind::Local;
    std::string text;
    Point at;
    int child = -1;                  // SheetPin: the child instance it leads into
    int net = -1;
    double angle = 0;                // text direction: 0 right, 90 up, 180 left, 270 down
    double size = 1.27;
    std::string shape;               // global/hierarchical/sheet pin: input, output, ...
};

// The box of a sub-sheet as drawn on its parent.
struct SchSheetBox {
    int sheet = 0;                   // where it's drawn
    int child = -1;                  // the instance it opens
    Point at, size;
    SchText name, file;
};

struct SchNode {
    int symbol, pin;                 // indexes into symbols / symbols[symbol].pins
};

struct SchNet {
    std::string name;
    std::vector<SchNode> nodes;      // pins of real parts (power symbols excluded)
};

struct Schematic {
    std::vector<SheetInstance> sheets;
    std::vector<SchSymbol> symbols;
    std::vector<SchWire> wires;
    std::vector<SchLabel> labels;
    std::vector<std::pair<int, Point>> junctions; // (sheet, position)
    std::vector<std::pair<int, Point>> no_connects;
    std::vector<SchSheetBox> sheet_boxes;
    std::vector<std::pair<int, SchText>> texts;     // free text notes
    std::vector<std::pair<int, std::string>> drawings; // lines/boxes drawn on sheets (SVG path data)
    std::map<std::string, SymbolDef> defs;
    std::vector<SchNet> nets;
    std::vector<std::string> warnings; // missing sheet files, etc.
};

// Reads a file by path relative to the root schematic's folder, or nullopt.
using FileReader = std::function<std::optional<std::string>(const std::string& rel)>;

// Loads the root sheet `root_file` and every sheet below it, then computes
// nets. Throws std::runtime_error if the root sheet can't be read or parsed.
Schematic load_schematic(const std::string& root_file, const FileReader& read);

} // namespace kigit
