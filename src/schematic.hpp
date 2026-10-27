// Schematic model: sheets, symbols, wires and labels of a KiCad project,
// plus the nets they form.
//
// KiCad doesn't store nets in .kicad_sch files. A wire is just two points;
// what it connects to is worked out from what touches it. connect() does that,
// following KiCad's rules for labels, power symbols and sheet hierarchy.
#pragma once

#include "board.hpp" // Point

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace kigit {

struct SheetInstance {
    std::string file;      // e.g. "GPIOs.kicad_sch", relative to the root's folder
    std::string name;      // sheet name, "" for the root
    std::string path;      // human path used in net names, e.g. "/owl_v1/GPIOs/"
    std::string uuid_path; // KiCad instance path, e.g. "/<root uuid>/<sheet uuid>"
    int parent = -1;       // index of the parent instance, -1 for the root
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
    int unit = 1;
    Point at;
    double angle = 0;
    bool mirror_x = false, mirror_y = false;
    bool power = false;              // power symbol (GND, +3.3V, ...)
    std::vector<SchPin> pins;
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
    std::vector<SchNet> nets;
    std::vector<std::string> warnings; // missing sheet files, etc.
};

// Reads a file by path relative to the root schematic's folder, or nullopt.
using FileReader = std::function<std::optional<std::string>(const std::string& rel)>;

// Loads the root sheet `root_file` and every sheet below it, then computes
// nets. Throws std::runtime_error if the root sheet can't be read or parsed.
Schematic load_schematic(const std::string& root_file, const FileReader& read);

} // namespace kigit
