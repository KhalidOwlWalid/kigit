#include "helpers.hpp"
#include "sch/bom.hpp"

#include <doctest/doctest.h>

#include <string>

using namespace kigit;
using namespace kigit::test;

namespace {

// A one-sheet schematic with the given symbols (lib Device:R, power:GND).
Schematic sheet(const std::string& symbols) {
    std::string text = R"((kicad_sch (version 20250114) (generator "eeschema") (uuid "root")
  (lib_symbols
    (symbol "Device:R" (symbol "R_1_1" (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))))
    (symbol "power:GND" (power) (symbol "GND_1_1" (pin power_in line (at 0 0 270) (length 0) (hide yes) (name "GND") (number "1")))))
)" + symbols + ")";
    return load_schematic("x.kicad_sch", [&](const std::string&) -> std::optional<std::string> { return text; });
}

std::string part(const std::string& ref, const std::string& value, const std::string& footprint,
                 const std::string& extra = "") {
    return "(symbol (lib_id \"Device:R\") (at 0 0 0) (unit 1) " + extra + "(property \"Reference\" \"" + ref +
           "\") (property \"Value\" \"" + value + "\") (property \"Footprint\" \"" + footprint + "\"))\n";
}

const BomLine& line_of(const Bom& bom, const std::string& ref) {
    for (const auto& l : bom.lines)
        for (const auto& r : l.refs)
            if (r == ref) return l;
    FAIL("no line with " << ref);
    throw;
}

} // namespace

TEST_SUITE("bom") {

TEST_CASE("parts are grouped into lines, in natural order") {
    Bom bom = make_bom(sheet(part("R10", "10k", "Resistor_SMD:R_0603_1608Metric") +
                             part("R2", "10k", "Resistor_SMD:R_0603_1608Metric") +
                             part("R1", "10k", "Resistor_SMD:R_0402_1005Metric") + // another footprint: its own line
                             part("C1", "100n", "Capacitor_SMD:C_0603_1608Metric")));
    REQUIRE(bom.lines.size() == 3);
    CHECK(bom.lines[0].refs == std::vector<std::string>{"C1"}); // C before R
    CHECK(bom.lines[1].refs == std::vector<std::string>{"R1"});
    CHECK(bom.lines[2].refs == std::vector<std::string>{"R2", "R10"}); // R2 before R10
    CHECK(bom.parts == 4);
    CHECK(line_of(bom, "R2").package == "0603");
    CHECK(line_of(bom, "R2").kind == "resistor");
    CHECK(ref_less("R2", "R10"));
    CHECK(!ref_less("R10", "R2"));
    CHECK(ref_less("U1A", "U1B"));
}

TEST_CASE("left out: power symbols, # references, excluded parts; a part in several units counts once") {
    Bom bom = make_bom(sheet(
        "(symbol (lib_id \"power:GND\") (at 0 0 0) (unit 1) (property \"Reference\" \"#PWR01\") (property \"Value\" \"GND\"))\n" +
        part("R1", "1k", "R_0603", "(in_bom no) ") + part("R2", "1k", "R_0603", "(exclude_from_bom yes) ") +
        part("U1", "LM358", "SOIC-8") + part("U1", "LM358", "SOIC-8", "") + part("R3", "1k", "R_0603")));
    REQUIRE(bom.lines.size() == 2);
    CHECK(line_of(bom, "U1").qty() == 1);
    CHECK(line_of(bom, "R3").qty() == 1);
    CHECK(bom.parts == 2);
}

TEST_CASE("part numbers from the usual field names; DNP from the flag, a field or the value") {
    Bom bom = make_bom(sheet(
        part("C1", "1u", "C_0603", "(property \"LCSC Part #\" \"C52923\") ") +
        part("U1", "STM32F103C8T6", "LQFP-48",
             "(property \"Manufacturer_Part_Number\" \"STM32F103C8T6\") (property \"MFR\" \"ST\") "
             "(property \"DigiKey\" \"497-6063-ND\") (property \"Mouser Part Number\" \"511-STM32F103C8T6\") "
             "(property \"Substitution\" \"GD32F103C8T6\") (property \"ki_keywords\" \"mcu\") ") +
        part("R1", "1k", "R_0603", "(dnp yes) ") + part("R2", "1k", "R_0603", "(property \"DNP\" \"1\") ") +
        part("R3", "DNP", "R_0805") + part("R4", "1k", "R_0603", "(property \"MPN\" \"~\") ")));
    const BomLine& c1 = line_of(bom, "C1");
    CHECK(c1.lcsc == "C52923");
    CHECK(c1.has_number());
    const BomLine& u1 = line_of(bom, "U1");
    CHECK(u1.mpn == "STM32F103C8T6");
    CHECK(u1.manufacturer == "ST");
    CHECK(u1.digikey == "497-6063-ND");
    CHECK(u1.mouser == "511-STM32F103C8T6");
    CHECK(u1.fields == std::map<std::string, std::string>{{"Substitution", "GD32F103C8T6"}}); // no KiCad internals
    CHECK(line_of(bom, "R1").dnp);
    CHECK(line_of(bom, "R2").dnp);
    CHECK(&line_of(bom, "R1") == &line_of(bom, "R2")); // both DNP 1k 0603: one line
    CHECK(line_of(bom, "R3").dnp);
    CHECK(!line_of(bom, "R4").dnp);
    CHECK(!line_of(bom, "R4").has_number()); // "~" is no part number
    CHECK(bom.dnp_parts == 3);
}

TEST_CASE("search queries and links") {
    Bom bom = make_bom(sheet(part("R1", "10kR", "Resistor_SMD:R_0603_1608Metric") +
                             part("R2", "5k1", "Resistor_SMD:R_0603_1608Metric") +
                             part("R3", "27R", "hackrf:GSG-0402") + part("R4", "4R7", "R_0805") +
                             part("C1", "100nF", "Capacitor_SMD:C_0402_1005Metric") +
                             part("Y1", "32k768", "Crystal:Crystal_SMD_MicroCrystal") +
                             part("U1", "FT230XS", "Package_SO:SSOP-16") +
                             part("U2", "LM358", "SOIC-8", "(property \"MPN\" \"LM358DR\") (property \"Mouser\" \"595-LM358DR\") ")));
    CHECK(line_of(bom, "R1").query == "10k 0603 resistor");
    CHECK(line_of(bom, "R2").query == "5.1k 0603 resistor");
    CHECK(line_of(bom, "R3").query == "27 ohm 0402 resistor");
    CHECK(line_of(bom, "R4").query == "4.7 ohm 0805 resistor");
    CHECK(line_of(bom, "C1").query == "100nF 0402 capacitor");
    CHECK(line_of(bom, "Y1").query == "32.768kHz crystal");
    CHECK(line_of(bom, "U1").query == "FT230XS");
    const BomLine& u2 = line_of(bom, "U2");
    CHECK(u2.query == "LM358DR");
    CHECK(search_url(u2, "digikey") == "https://www.digikey.com/en/products/result?keywords=LM358DR");
    CHECK(search_url(u2, "mouser") == "https://www.mouser.com/c/?q=595-LM358DR"); // its own number there
    CHECK(search_url(line_of(bom, "R1"), "lcsc") == "https://www.lcsc.com/search?q=10k+0603+resistor");
}

TEST_CASE("CSV quotes what needs it") {
    Bom bom = make_bom(sheet(part("J1", "Conn, \\\"USB\\\"", "USB_C"))); // KiCad escapes the quotes
    std::string csv = bom_csv(bom);
    CHECK(csv.starts_with("Qty,References,Value,Footprint,Manufacturer,MPN,Digi-Key,Mouser,LCSC,DNP,Description\n"));
    CHECK(csv.find("1,J1,\"Conn, \"\"USB\"\"\",USB_C,") != std::string::npos);
}

} // TEST_SUITE
