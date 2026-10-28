#include "utils/sexpr.hpp"

#include <doctest/doctest.h>

#include <stdexcept>

using namespace kigit;

TEST_SUITE("sexpr") {

TEST_CASE("nested lists, atoms and lookups") {
    sexpr::Node root = sexpr::parse(R"((kicad_pcb (version 20260206) (net "GND") (at 1.5 -2 90)))");
    REQUIRE(root.children.size() == 1);
    const sexpr::Node& pcb = root.children[0];
    CHECK(pcb.name() == "kicad_pcb");
    CHECK(pcb.child("version")->num(0) == 20260206);
    CHECK(pcb.child("net")->arg(0) == "GND");
    CHECK(pcb.child("net")->arg_node(0)->quoted);
    const sexpr::Node* at = pcb.child("at");
    CHECK(at->num(0) == doctest::Approx(1.5));
    CHECK(at->num(1) == doctest::Approx(-2));
    CHECK(at->num(2) == doctest::Approx(90));
    CHECK(at->arg_count() == 3);
    CHECK(pcb.child("missing") == nullptr);
}

TEST_CASE("quoted strings keep spaces, brackets and escapes") {
    sexpr::Node root = sexpr::parse(R"((property "Description" "a (b) \"c\" d\\e"))");
    const sexpr::Node& p = root.children[0];
    CHECK(p.arg(0) == "Description");
    CHECK(sexpr::unescape(p.arg(1)) == R"(a (b) "c" d\e)");
}

TEST_CASE("each() visits every child list with a name") {
    sexpr::Node root = sexpr::parse("(x (pad 1) (net 2) (pad 3))");
    int sum = 0;
    root.children[0].each("pad", [&](const sexpr::Node& n) { sum += static_cast<int>(n.num(0)); });
    CHECK(sum == 4);
}

TEST_CASE("num() falls back on missing or non-numeric arguments") {
    sexpr::Node root = sexpr::parse("(x abc)");
    CHECK(root.children[0].num(0, -1) == -1);
    CHECK(root.children[0].num(5, 7) == 7);
}

TEST_CASE("malformed input is rejected with a line number") {
    CHECK_THROWS_AS(sexpr::parse("(a (b)"), std::runtime_error);
    CHECK_THROWS_AS(sexpr::parse("(a))"), std::runtime_error);
    CHECK_THROWS_AS(sexpr::parse("(a \"unterminated)"), std::runtime_error);
    try {
        sexpr::parse("(a\n(b\n");
        FAIL("expected an error");
    } catch (const std::runtime_error& e) {
        CHECK(std::string(e.what()).find("line") != std::string::npos);
    }
}

}
