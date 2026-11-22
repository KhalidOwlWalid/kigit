#include "sch/bom.hpp"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <regex>
#include <set>
#include <tuple>

namespace kigit {

namespace {

std::string lower(std::string s) {
    for (char& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

// "LCSC Part #" -> "lcscpart", "Manufacturer_Part_Number" -> "manufacturerpartnumber".
std::string key_of(const std::string& name) {
    std::string out;
    for (char c : name)
        if (std::isalnum(static_cast<unsigned char>(c))) out += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return out;
}

// The field names people use for each part number.
const std::set<std::string> kMpn = {"mpn", "manufacturerpartnumber", "manufacturerpn", "mfrpn", "mfrpartnumber",
                                    "mfrno", "mfgpn", "mfgpartnumber", "partnumber", "pn", "mpn1"};
const std::set<std::string> kMaker = {"manufacturer", "manufacturername", "mfr", "mfg", "manufacturer1"};
const std::set<std::string> kDigikey = {"digikey", "digikeypn", "digikeypartnumber", "digikeypartno", "digikeypart",
                                        "dk", "dkpn"};
const std::set<std::string> kMouser = {"mouser", "mouserpn", "mouserpartnumber", "mouserpartno", "mouserpart"};
const std::set<std::string> kLcsc = {"lcsc", "lcscpart", "lcscpartnumber", "lcscpn", "lcscpartno", "jlcpcbpart",
                                     "jlcpcbpartnumber"};

bool empty_value(const std::string& v) { return v.empty() || v == "~"; }

// Fields that say nothing about the part to buy (KiCad's own, sheet links).
bool internal(const std::string& name) {
    return name.starts_with("ki_") || name == "Intersheetrefs" || name.starts_with("Sim.") || name == "Datasheet" ||
           name == "Description";
}

std::string prefix_of(const std::string& ref) {
    std::string p;
    for (char c : ref) {
        if (std::isalpha(static_cast<unsigned char>(c))) p += static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
        else break;
    }
    return p;
}

std::string kind_of(const SchSymbol& s) {
    std::string p = prefix_of(s.ref), fp = lower(s.footprint), lib = lower(s.lib_id);
    if (fp.find("led") != std::string::npos || lib.find("led") != std::string::npos) return "led";
    if (p == "R") return "resistor";
    if (p == "C") return "capacitor";
    if (p == "L") return "inductor";
    if (p == "FB") return "ferrite";
    if (p == "D") return "diode";
    if (p == "Y" || p == "X") return "crystal";
    if (p == "J" || p == "P" || p == "CN" || lib.rfind("connector", 0) == 0) return "connector";
    return "other";
}

// "Resistor_SMD:R_0603_1608Metric" -> "0603"; otherwise the footprint's own name.
std::string package_of(const std::string& footprint) {
    std::string name = footprint.substr(footprint.find(':') == std::string::npos ? 0 : footprint.find(':') + 1);
    static const std::regex chip(R"((?:^|[_-])(01005|0201|0402|0603|0805|1206|1210|1812|2010|2512)(?:[_-]|$))");
    std::smatch m;
    if (std::regex_search(name, m, chip)) return m[1];
    return name;
}

// A capacitance or inductance as distributors search for it: "1n8" / "1n8F"
// -> "1.8nF", "4u7" -> "4.7uF", "2p2" -> "2.2pF", "100n" -> "100nF",
// "4n7H" -> "4.7nH" (unit F or H). Anything else as it is.
std::string farads_or_henries(const std::string& value, const std::string& unit) {
    std::string v = value;
    for (const char* micro : {"\xC2\xB5", "\xCE\xBC"}) // µ and μ
        for (size_t at; (at = v.find(micro)) != std::string::npos;) v.replace(at, 2, "u");
    static const std::regex rkm(R"(^(\d+)([pnum])(\d+)\s*([FfHh])?$)");
    static const std::regex plain(R"(^(\d+(?:\.\d+)?)\s*([pnum])\s*([FfHh])?$)");
    std::smatch m;
    if (std::regex_match(v, m, rkm)) return m[1].str() + "." + m[3].str() + m[2].str() + unit;
    if (std::regex_match(v, m, plain)) return m[1].str() + m[2].str() + unit;
    return value;
}

// A resistance as distributors search for it: "10kR" -> "10k", "5k1" ->
// "5.1k", "4R7" -> "4.7 ohm", "27R" -> "27 ohm". Anything else as it is.
std::string ohms(const std::string& value) {
    static const std::regex rkm(R"(^(\d+)([RrKkM])(\d+)\s*(?:R|r|ohms?|Ohms?|\xCE\xA9)?$)"); // 5k1, 5k1R, 4R7, 1M2
    static const std::regex plain(R"(^(\d+(?:\.\d+)?)\s*([kKM]?)\s*(?:R|r|ohms?|Ohms?|\xCE\xA9)?$)"); // 10kR, 27R, 4.7k
    auto unit = [](std::string m) { return m == "K" || m == "k" ? std::string("k") : m == "M" ? std::string("M") : ""; };
    std::smatch m;
    if (std::regex_match(value, m, rkm)) {
        std::string u = unit(m[2]);
        return m[1].str() + "." + m[3].str() + (u.empty() ? " ohm" : u);
    }
    if (std::regex_match(value, m, plain)) {
        std::string u = unit(m[2]);
        return m[1].str() + (u.empty() ? " ohm" : u);
    }
    return value;
}

std::string url_encode(const std::string& s) {
    std::string out;
    char buf[4];
    for (unsigned char c : s) {
        if (std::isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') out += static_cast<char>(c);
        else if (c == ' ') out += '+';
        else {
            std::snprintf(buf, sizeof buf, "%%%02X", c);
            out += buf;
        }
    }
    return out;
}

std::string csv_cell(const std::string& s) {
    if (s.find_first_of(",\"\n\r") == std::string::npos) return s;
    std::string out = "\"";
    for (char c : s) out += c == '"' ? std::string("\"\"") : std::string(1, c);
    return out + "\"";
}

std::string join(const std::vector<std::string>& v, const std::string& sep) {
    std::string out;
    for (size_t i = 0; i < v.size(); ++i) out += (i ? sep : "") + v[i];
    return out;
}

} // namespace

namespace {

// A footprint name's part after the library ("Connector_JST:JST_SH_..." -> "JST_SH_...").
std::string fp_name(const std::string& footprint) {
    auto c = footprint.find(':');
    return c == std::string::npos ? footprint : footprint.substr(c + 1);
}

// Pieces of a footprint name that describe it rather than name a part.
bool descriptive(const std::string& t) {
    static const std::regex re(
        R"(^(\d+x\d+.*|P\d.*|\d+(\.\d+)?(x\d+(\.\d+)?)?mm.*|\d+MP|\d*Metric|Vertical|Horizontal|Angled|Straight|SMD|THT|)"
        R"(Pad.*|Drill.*|Pitch.*|Handsoldering|HandSoldering|Clamped|Shielded|Unshielded|Top|Bottom|Side|Plug|Receptacle|)"
        R"((SOIC|SOP|SSOP|TSSOP|MSOP|QFN|DFN|VQFN|WQFN|LQFP|TQFP|QFP|BGA|SOT|SOD|TO|DIP|PDIP|SIP|PLCC|LGA|WSON|SON|USON|)"
        R"(UDFN|HVQFN|SC|DPAK|D2PAK|MiniMELF|MELF|SMA|SMB|SMC|PowerPAK|ESOP|HTSSOP|eTSSOP|TSOT|uSOP)-?\d.*)$)",
        std::regex::icase);
    return std::regex_match(t, re);
}

} // namespace

std::string footprint_part_number(const std::string& footprint) {
    std::string name = fp_name(footprint);
    std::vector<std::string> parts;
    std::string cur;
    for (char c : name) {
        if (c == '_') { parts.push_back(cur); cur.clear(); } else cur += c;
    }
    parts.push_back(cur);
    for (const auto& t : parts) {
        if (t.size() < 6 || descriptive(t)) continue;
        bool digit = false, letter = false, dash = false;
        for (unsigned char c : t) digit |= std::isdigit(c) != 0, letter |= std::isalpha(c) != 0, dash |= c == '-';
        // A part number has digits and letters (BM04B-SRSS-TB, USB4085), or is digits with a dash (53047-0410).
        if (!(digit && (letter || dash))) continue;
        // "USB4105-xx-A": xx stands for options the library leaves open; search the part before it.
        static const std::regex open_options(R"([-_.]?[xX]{2,}.*$)");
        std::string pn = std::regex_replace(t, open_options, "");
        if (pn.size() >= 4) return pn;
    }
    return "";
}

bool value_is_part_number(const std::string& v) {
    if (v.size() < 5 || v.find(' ') != std::string::npos) return false;
    static const std::regex symbol(R"(^(Conn_|Screw_Terminal|SW_|LED|Jumper|TestPoint|Fuse|Battery|MountingHole|Fiducial|)"
                                   R"(USB_[A-Z]|Barrel_Jack|AudioJack|Micro_SD|SD_Card|SIM_Card|RJ45|Antenna|Buzzer|Speaker|)"
                                   R"(Crystal|Resonator|Thermistor|Varistor|Polyfuse|Net-Tie|NetTie).*)",
                                   std::regex::icase);
    if (std::regex_match(v, symbol)) return false;
    bool digit = false, letter = false;
    for (unsigned char c : v) digit |= std::isdigit(c) != 0, letter |= std::isalpha(c) != 0;
    return digit && letter;
}

std::pair<std::string, std::string> query_of(const BomLine& l) {
    if (!l.mpn.empty()) return {l.mpn, "mpn"};
    // Copper on the board, nothing to buy.
    static const std::regex bare(R"(^(TestPoint|MountingHole|Fiducial|NetTie):.*)");
    if (std::regex_match(l.footprint, bare)) return {"", "nothing to buy"};
    static const std::map<std::string, std::string> word = {{"resistor", "resistor"}, {"capacitor", "capacitor"},
                                                            {"inductor", "inductor"}, {"ferrite", "ferrite bead"},
                                                            {"led", "LED"}, {"crystal", "crystal"}};
    auto w = word.find(l.kind);
    if (w != word.end()) {
        std::string q = l.kind == "resistor" || l.kind == "ferrite" ? ohms(l.value)
                        : l.kind == "capacitor" ? farads_or_henries(l.value, "F")
                        : l.kind == "inductor"  ? farads_or_henries(l.value, "H")
                                                : l.value;
        static const std::regex khz(R"(^(\d+)[kK](\d+)$)"); // 32k768 -> 32.768kHz
        if (l.kind == "crystal") q = std::regex_replace(q, khz, "$1.$2kHz");
        if (!l.package.empty() && l.package != l.footprint && l.kind != "crystal") q += " " + l.package;
        if (lower(q).find(lower(w->second)) == std::string::npos) q += " " + w->second;
        return {q, "passive"};
    }
    // A connector's value is usually what it's for ("I2C"): its footprint names the part.
    bool connector = l.kind == "connector";
    std::string in_fp = footprint_part_number(l.footprint);
    if (!in_fp.empty() && (connector || !value_is_part_number(l.value))) return {in_fp, "footprint"};
    if (value_is_part_number(l.value) && !connector) return {l.value, "value"};
    // Neither: the footprint's own words ("JST SH 1x04 P1.00mm Vertical") and what it is.
    std::string words = fp_name(l.footprint);
    std::replace(words.begin(), words.end(), '_', ' ');
    if (connector && lower(words).find("conn") == std::string::npos) words += " connector";
    if (!words.empty() && words != " connector") return {words, "footprint words"};
    return {l.value, "value"};
}

bool ref_less(const std::string& a, const std::string& b) {
    size_t i = 0, j = 0;
    while (i < a.size() && j < b.size()) {
        bool da = std::isdigit(static_cast<unsigned char>(a[i])), db = std::isdigit(static_cast<unsigned char>(b[j]));
        if (da && db) {
            size_t ie = i, je = j;
            while (ie < a.size() && std::isdigit(static_cast<unsigned char>(a[ie]))) ++ie;
            while (je < b.size() && std::isdigit(static_cast<unsigned char>(b[je]))) ++je;
            std::string na = a.substr(i, ie - i), nb = b.substr(j, je - j);
            na.erase(0, std::min(na.find_first_not_of('0'), na.size() - 1));
            nb.erase(0, std::min(nb.find_first_not_of('0'), nb.size() - 1));
            if (na.size() != nb.size()) return na.size() < nb.size();
            if (na != nb) return na < nb;
            i = ie, j = je;
        } else {
            if (a[i] != b[j]) return a[i] < b[j];
            ++i, ++j;
        }
    }
    return a.size() - i < b.size() - j;
}

Bom make_bom(const Schematic& sch) {
    Bom bom;
    std::map<std::tuple<std::string, std::string, std::string, std::string, std::string, std::string, std::string, bool>,
             size_t>
        index;
    std::set<std::string> seen; // a part in several units: once
    std::map<std::string, std::map<std::string, int>> names; // kind -> spelling -> uses
    for (const SchSymbol& s : sch.symbols) {
        if (s.power || !s.in_bom || s.ref.empty() || s.ref[0] == '#' || s.ref.ends_with("?")) continue;
        if (!seen.insert(s.ref).second) continue;
        BomLine l;
        l.value = s.value;
        l.footprint = s.footprint;
        l.lib_id = s.lib_id;
        l.dnp = s.dnp;
        for (const auto& [name, v] : s.fields) {
            if (empty_value(v)) continue;
            std::string k = key_of(name);
            if (kMpn.count(k)) l.mpn = v, ++names["mpn"][name];
            else if (kMaker.count(k)) l.manufacturer = v, ++names["manufacturer"][name];
            else if (kDigikey.count(k)) l.digikey = v, ++names["digikey"][name];
            else if (kMouser.count(k)) l.mouser = v, ++names["mouser"][name];
            else if (kLcsc.count(k)) l.lcsc = v, ++names["lcsc"][name];
            else if (k == "dnp") l.dnp = l.dnp || !(lower(v) == "no" || v == "0" || lower(v) == "false");
            else if (name == "Description") l.description = v;
            else if (name == "Datasheet") l.datasheet = v;
            else if (!internal(name)) l.fields[name] = v;
        }
        // Before KiCad 7 there was no DNP flag: a "DNP" field or value said it.
        if (lower(l.value) == "dnp") l.dnp = true;
        auto key = std::tuple{l.value, l.footprint, l.mpn, l.manufacturer, l.digikey, l.mouser, l.lcsc, l.dnp};
        auto [it, fresh] = index.try_emplace(key, bom.lines.size());
        if (fresh) {
            l.kind = kind_of(s);
            l.package = package_of(s.footprint);
            std::tie(l.query, l.query_from) = query_of(l);
            bom.lines.push_back(std::move(l));
        }
        bom.lines[it->second].refs.push_back(s.ref);
    }
    const std::map<std::string, std::string> plain = {
        {"mpn", "MPN"}, {"manufacturer", "Manufacturer"}, {"digikey", "DigiKey"}, {"mouser", "Mouser"}, {"lcsc", "LCSC"}};
    for (const auto& [kind, name] : plain) {
        bom.field_names[kind] = name;
        int best = 0;
        for (const auto& [spelling, n] : names[kind])
            if (n > best) best = n, bom.field_names[kind] = spelling;
    }
    for (auto& l : bom.lines) {
        std::sort(l.refs.begin(), l.refs.end(), ref_less);
        bom.parts += l.qty();
        if (l.dnp) bom.dnp_parts += l.qty();
        if (!l.has_number()) ++bom.without_number;
    }
    std::sort(bom.lines.begin(), bom.lines.end(), [](const BomLine& a, const BomLine& b) {
        std::string pa = prefix_of(a.refs[0]), pb = prefix_of(b.refs[0]);
        if (pa != pb) return pa < pb;
        return ref_less(a.refs[0], b.refs[0]);
    });
    return bom;
}

std::string search_url(const BomLine& l, const std::string& site) {
    if (site == "digikey")
        return "https://www.digikey.com/en/products/result?keywords=" + url_encode(!l.digikey.empty() ? l.digikey : l.query);
    if (site == "mouser") return "https://www.mouser.com/c/?q=" + url_encode(!l.mouser.empty() ? l.mouser : l.query);
    if (site == "lcsc") return "https://www.lcsc.com/search?q=" + url_encode(!l.lcsc.empty() ? l.lcsc : l.query);
    return "";
}

nlohmann::json bom_json(const Bom& bom) {
    nlohmann::json lines = nlohmann::json::array();
    for (const auto& l : bom.lines)
        lines.push_back({{"refs", l.refs},
                         {"qty", l.qty()},
                         {"value", l.value},
                         {"footprint", l.footprint},
                         {"package", l.package},
                         {"kind", l.kind},
                         {"lib_id", l.lib_id},
                         {"description", l.description},
                         {"datasheet", l.datasheet},
                         {"mpn", l.mpn},
                         {"manufacturer", l.manufacturer},
                         {"digikey", l.digikey},
                         {"mouser", l.mouser},
                         {"lcsc", l.lcsc},
                         {"dnp", l.dnp},
                         {"fields", l.fields},
                         {"query", l.query},
                         {"query_from", l.query_from},
                         {"links",
                          {{"digikey", search_url(l, "digikey")},
                           {"mouser", search_url(l, "mouser")},
                           {"lcsc", search_url(l, "lcsc")}}}});
    return {{"lines", lines},
            {"field_names", bom.field_names},
            {"summary",
             {{"lines", bom.lines.size()},
              {"parts", bom.parts},
              {"dnp_parts", bom.dnp_parts},
              {"without_number", bom.without_number}}}};
}

std::string bom_csv(const Bom& bom) {
    std::string out = "Qty,References,Value,Footprint,Manufacturer,MPN,Digi-Key,Mouser,LCSC,DNP,Description\n";
    for (const auto& l : bom.lines) {
        std::vector<std::string> cells = {std::to_string(l.qty()), join(l.refs, " "), l.value,    l.footprint,
                                          l.manufacturer,          l.mpn,             l.digikey, l.mouser,
                                          l.lcsc,                  l.dnp ? "DNP" : "", l.description};
        for (size_t i = 0; i < cells.size(); ++i) out += (i ? "," : "") + csv_cell(cells[i]);
        out += "\n";
    }
    return out;
}

std::string bom_table(const Bom& bom) {
    auto clip = [](std::string s, size_t n) { return s.size() <= n ? s : s.substr(0, n - 1) + "~"; };
    std::string out;
    char row[512];
    std::snprintf(row, sizeof row, "%4s  %-24s %-18s %-22s %s\n", "Qty", "References", "Value", "Package", "Part number");
    out += row;
    for (const auto& l : bom.lines) {
        std::string number = !l.mpn.empty() ? (l.manufacturer.empty() ? l.mpn : l.manufacturer + " " + l.mpn)
                             : !l.lcsc.empty()    ? "LCSC " + l.lcsc
                             : !l.digikey.empty() ? "Digi-Key " + l.digikey
                             : !l.mouser.empty()  ? "Mouser " + l.mouser
                                                  : "-";
        std::snprintf(row, sizeof row, "%4d  %-24s %-18s %-22s %s%s\n", l.qty(), clip(join(l.refs, " "), 24).c_str(),
                      clip(l.value, 18).c_str(), clip(l.package, 22).c_str(), number.c_str(), l.dnp ? "  (DNP)" : "");
        out += row;
    }
    std::snprintf(row, sizeof row, "\n%zu lines, %d parts%s; %d lines without a part number\n", bom.lines.size(),
                  bom.parts, bom.dnp_parts ? (", " + std::to_string(bom.dnp_parts) + " not populated").c_str() : "",
                  bom.without_number);
    out += row;
    return out;
}

} // namespace kigit
