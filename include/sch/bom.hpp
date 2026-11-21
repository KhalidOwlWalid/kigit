#pragma once
// The bill of materials from a schematic: parts grouped into lines (same
// value, footprint, part numbers and DNP), with the part numbers found in
// the usual field names and a search query for distributors.
#include "sch/schematic.hpp"

#include <nlohmann/json.hpp>

#include <map>
#include <string>
#include <vector>

namespace kigit {

struct BomLine {
    std::vector<std::string> refs;  // R1, R2, R10: in natural order
    std::string value, footprint, lib_id, description, datasheet;
    std::string package;            // "0603" for chip parts, else the footprint's name
    std::string kind;               // resistor, capacitor, inductor, ferrite, led, diode, crystal, connector, other
    std::string mpn, manufacturer, digikey, mouser, lcsc; // from the parts' fields ("" if none)
    bool dnp = false;
    std::map<std::string, std::string> fields; // the rest of the fields, as written (no KiCad internals)
    std::string query;              // what to search for: a part number, or "10k 0603 resistor"
    std::string query_from;         // where it came from: mpn, passive, value, footprint, footprint words

    int qty() const { return static_cast<int>(refs.size()); }
    bool has_number() const { return !mpn.empty() || !digikey.empty() || !mouser.empty() || !lcsc.empty(); }
};

struct Bom {
    std::vector<BomLine> lines;
    int parts = 0, dnp_parts = 0, without_number = 0; // without_number: lines
    // The field name this project uses for each kind of part number (the
    // most used spelling, e.g. "LCSC Part #"), else the plain one ("LCSC").
    // Keys: mpn, manufacturer, digikey, mouser, lcsc.
    std::map<std::string, std::string> field_names;
};

// Every part that goes on the BOM: not power symbols or "#" references, not
// excluded from the BOM; a part in several units counts once.
Bom make_bom(const Schematic& sch);

// The maker's part number in a KiCad footprint's name, which KiCad's
// libraries put there for connectors and the like:
// "Connector_JST:JST_SH_BM04B-SRSS-TB_1x04-1MP_P1.00mm_Vertical" ->
// "BM04B-SRSS-TB". "" when there's none (PinHeader_1x04_P2.54mm, SOIC-8...).
std::string footprint_part_number(const std::string& footprint);

// Whether a Value looks like a part name ("STM32F103C8T6", "LM358DR"), not
// a label ("I2C", "USB", "Debug") or a symbol's name ("Conn_01x04").
bool value_is_part_number(const std::string& value);

// What to search a distributor for, for a line without a part number, and
// where it came from: the MPN; a passive's value + package; the part number
// in the footprint (for connectors, or when the value is a label); the value
// when it's a part name; else the footprint's own words + the kind.
std::pair<std::string, std::string> query_of(const BomLine& line);

// Searching a distributor's site for a line: its own part number there, the
// MPN, or the query. site: "digikey", "mouser", "lcsc".
std::string search_url(const BomLine& line, const std::string& site);

// "R1-R4, R7" style lists are left to the caller; these are plain.
nlohmann::json bom_json(const Bom& bom);
std::string bom_csv(const Bom& bom);
std::string bom_table(const Bom& bom); // for a terminal

// Natural order for references: R2 before R10.
bool ref_less(const std::string& a, const std::string& b);

} // namespace kigit
