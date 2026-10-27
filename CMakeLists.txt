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

# Embed the HTML viewer template into the binary.
set(VIEWER_SRC ${CMAKE_CURRENT_SOURCE_DIR}/resources/viewer.html)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${VIEWER_SRC})
file(READ ${VIEWER_SRC} KIGIT_VIEWER_HTML)
configure_file(src/viewer_template.hpp.in
               ${CMAKE_CURRENT_BINARY_DIR}/generated/viewer_template.hpp @ONLY)

add_executable(kigit
  src/main.cpp
  src/sexpr.cpp
  src/board.cpp
  src/git.cpp
  src/diff.cpp
  src/html.cpp
  src/locate.cpp
)
target_include_directories(kigit PRIVATE src ${CMAKE_CURRENT_BINARY_DIR}/generated)
target_compile_definitions(kigit PRIVATE KIGIT_VERSION="${PROJECT_VERSION}")
target_link_libraries(kigit PRIVATE nlohmann_json::nlohmann_json)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(kigit PRIVATE -Wall -Wextra -Wpedantic)
endif()

install(TARGETS kigit RUNTIME DESTINATION bin)
