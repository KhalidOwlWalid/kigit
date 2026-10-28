// Integration tests on a throwaway git repo (see make_fixture_repo in helpers.cpp).
#include "git/git.hpp"
#include "helpers.hpp"
#include "git/locate.hpp"

#include <doctest/doctest.h>

#include <algorithm>

using namespace kigit;
using namespace kigit::test;

TEST_SUITE("git") {

TEST_CASE("revisions resolve; unknown ones are errors") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string root = tmp.path().string();

    git::Revision head = git::resolve(root, "HEAD");
    CHECK(head.hash.size() == 40);
    CHECK(head.subject == "move project folder");
    CHECK(git::resolve(root, "HEAD~3").subject == "v1: first board");
    CHECK(git::resolve(root, "LOCAL").local);
    CHECK_THROWS(git::resolve(root, "no-such-commit"));
    CHECK(git::is_ancestor(root, git::resolve(root, "HEAD~3"), head));
    CHECK(!git::is_ancestor(root, head, git::resolve(root, "HEAD~3")));
}

TEST_CASE("log: everything, limited, by date and by path") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string root = tmp.path().string();

    git::LogQuery all;
    std::vector<git::Commit> commits = git::log(root, all);
    REQUIRE(commits.size() == 4);
    CHECK(commits[0].subject == "move project folder"); // newest first
    CHECK(git::count(root, all) == 4);

    git::LogQuery two;
    two.max_count = 2;
    CHECK(git::log(root, two).size() == 2);
    CHECK(git::count(root, two) == 4); // count ignores the limit

    git::LogQuery feb_on;
    feb_on.since = "2025-02-01 00:00:00";
    CHECK(git::log(root, feb_on).size() == 3);

    git::LogQuery docs;
    docs.paths = {"README.md"};
    REQUIRE(git::log(root, docs).size() == 1);
    CHECK(git::log(root, docs)[0].subject == "docs only");
}

TEST_CASE("past_paths follows the project folder rename") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::vector<std::string> paths = git::past_paths(tmp.path().string(), "board/demo.kicad_pcb");
    CHECK(std::find(paths.begin(), paths.end(), "board/demo.kicad_pcb") != paths.end());
    CHECK(std::find(paths.begin(), paths.end(), "hw/demo.kicad_pcb") != paths.end());
}

TEST_CASE("a moved board is found in older commits by its contents") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string root = tmp.path().string();
    git::Revision v1 = git::resolve(root, "HEAD~3");
    CHECK(!read_board_at(root, "board/demo.kicad_pcb", v1)); // not there yet

    Board latest = load_board(read_text(tmp / "board/demo.kicad_pcb"));
    BoardSource src = find_similar_board(root, "board/demo.kicad_pcb", v1, latest);
    CHECK(src.rel == "hw/demo.kicad_pcb");
    CHECK(src.relocated);
    CHECK(src.score > 0.5);
}

TEST_CASE("an unrelated board is not mistaken for the project") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string root = tmp.path().string();
    git::Revision v1 = git::resolve(root, "HEAD~3");
    Board other = load_board(R"((kicad_pcb (version 20260206) (layers (0 "F.Cu" signal))
        (footprint "X" (layer "F.Cu") (at 0 0) (property "Reference" "Q99")
          (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "OTHER")))))");
    CHECK_THROWS(find_similar_board(root, "board/demo.kicad_pcb", v1, other));
}

TEST_CASE("uncommitted changes are listed") {
    TempDir tmp;
    make_fixture_repo(tmp.path());
    std::string root = tmp.path().string();
    CHECK(git::changed_files(root, "board").empty());
    write_text(tmp / "board/notes.txt", "x");
    std::vector<std::string> changed = git::changed_files(root, "board");
    CHECK(changed == std::vector<std::string>{"board/notes.txt"});
}

}
