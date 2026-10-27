cmake_minimum_required(VERSION 3.16)
project(kigit VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# nlohmann_json: use the system package if present, otherwise download it.
find_package(nlohmann_json 3.2 QUIET)
if(NOT nlohmann_json_FOUND)
  include(FetchContent)
  FetchContent_Declare(json
    URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz)
  FetchContent_MakeAvailable(json)
endif()

# Embed the HTML viewer into the binary: the page shell plus its scripts,
# combined into one self-contained file.
set(VIEWER_DIR ${CMAKE_CURRENT_SOURCE_DIR}/resources)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
  ${VIEWER_DIR}/viewer.html ${VIEWER_DIR}/pcb.js ${VIEWER_DIR}/sch.js ${VIEWER_DIR}/shell.js)
file(READ ${VIEWER_DIR}/viewer.html KIGIT_VIEWER_HTML)
foreach(part PCB SCH SHELL)
  string(TOLOWER ${part} name)
  file(READ ${VIEWER_DIR}/${name}.js script)
  string(REPLACE "/*@KIGIT_${part}_JS@*/" "${script}" KIGIT_VIEWER_HTML "${KIGIT_VIEWER_HTML}")
endforeach()
configure_file(src/viewer_template.hpp.in
               ${CMAKE_CURRENT_BINARY_DIR}/generated/viewer_template.hpp @ONLY)

# Everything except main() is a library, so the tests can use it directly.
add_library(kigit_core STATIC
  src/sexpr.cpp
  src/board.cpp
  src/git.cpp
  src/diff.cpp
  src/html.cpp
  src/locate.cpp
  src/schematic.cpp
  src/sch_diff.cpp
  src/netcheck.cpp
)
target_include_directories(kigit_core PUBLIC src ${CMAKE_CURRENT_BINARY_DIR}/generated)
target_compile_definitions(kigit_core PUBLIC KIGIT_VERSION="${PROJECT_VERSION}")
target_link_libraries(kigit_core PUBLIC nlohmann_json::nlohmann_json)

add_executable(kigit src/main.cpp)
target_link_libraries(kigit PRIVATE kigit_core)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(kigit_core PRIVATE -Wall -Wextra -Wpedantic)
  target_compile_options(kigit PRIVATE -Wall -Wextra -Wpedantic)
endif()

option(KIGIT_BUILD_TESTS "Build the test suite (ctest)" ON)
if(KIGIT_BUILD_TESTS)
  enable_testing()
  add_subdirectory(tests)
endif()

install(TARGETS kigit RUNTIME DESTINATION bin)
# The Python GUI (kigit gui) is found at <prefix>/share/kigit/gui.
install(DIRECTORY gui/ DESTINATION share/kigit/gui
        PATTERN ".venv" EXCLUDE PATTERN "__pycache__" EXCLUDE PATTERN "uv.lock" EXCLUDE)
