
# Use a modern minimum version compatible with your main project
cmake_minimum_required(VERSION 3.16)

project(aspl CXX)

# --- Python detection ---
# Default to your known working interpreter
set(DEFAULT_PYTHON_EXECUTABLE "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3")

# Allow user to override with -DPYTHON_EXECUTABLE=...
if(NOT PYTHON_EXECUTABLE)
  set(PYTHON_EXECUTABLE "${DEFAULT_PYTHON_EXECUTABLE}" CACHE FILEPATH "Python interpreter to use")
endif()

# Check if the specified Python executable exists
if(NOT EXISTS "${PYTHON_EXECUTABLE}")
  message(WARNING "libASPL: Specified Python executable '${PYTHON_EXECUTABLE}' not found. Falling back to system 'python3'.")
  find_program(PYTHON_EXECUTABLE_FALLBACK python3 REQUIRED)
  set(PYTHON_EXECUTABLE "${PYTHON_EXECUTABLE_FALLBACK}" CACHE FILEPATH "Python interpreter fallback" FORCE)
endif()

# Final check
if(NOT EXISTS "${PYTHON_EXECUTABLE}")
  message(FATAL_ERROR "libASPL: Could not find a valid Python executable.")
endif()

message(STATUS "libASPL: Final Python interpreter: ${PYTHON_EXECUTABLE}")

# --- Version Handling ---
# Attempt to get version from git tag, provide a fallback
find_package(Git QUIET)
set(DEFAULT_VERSION "0.0.0-local") # Fallback version

if(GIT_FOUND)
  execute_process(
    COMMAND ${GIT_EXECUTABLE} describe --tags --abbrev=0
    WORKING_DIRECTORY "${PROJECT_SOURCE_DIR}"
    OUTPUT_VARIABLE GIT_TAG_RAW
    ERROR_QUIET
    OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE GIT_RESULT
  )
  if(GIT_RESULT EQUAL 0 AND GIT_TAG_RAW)
    string(REGEX MATCH "v?([0-9.]+)" GIT_TAG_MATCH "${GIT_TAG_RAW}")
    if(CMAKE_MATCH_1)
      set(PACKAGE_VERSION "${CMAKE_MATCH_1}")
      message(STATUS "libASPL: Detected version from git tag: ${PACKAGE_VERSION}")
    else()
      set(PACKAGE_VERSION "${DEFAULT_VERSION}")
      message(WARNING "libASPL: Could not parse version from git tag: ${GIT_TAG_RAW}. Using default: ${PACKAGE_VERSION}")
    endif()
  else()
    message(WARNING "libASPL: 'git describe --tags' failed or no tags found. Using default version: ${DEFAULT_VERSION}")
    set(PACKAGE_VERSION "${DEFAULT_VERSION}")
  endif()
else()
  message(WARNING "libASPL: Git not found. Using default version: ${DEFAULT_VERSION}")
  set(PACKAGE_VERSION "${DEFAULT_VERSION}")
endif()
# --- End Version Handling ---

set(PACKAGE_NAME libASPL)
set(LIB_TARGET libASPL) # Target name for the library
set(LIB_NAME ASPL)    # Output name for the library file
set(TEST_NAME aspl-test)

# --- Build Configuration ---
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE "Release" CACHE STRING "Build type (Release, Debug, etc.)" FORCE)
endif()
message(STATUS "libASPL: Build type: ${CMAKE_BUILD_TYPE}")

set(CMAKE_CXX_STANDARD 17) # Keep C++17 as required by original libASPL
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON) # Useful for tooling

# --- Compiler Flags ---
set(ASPL_COMPILE_FLAGS "")
list(APPEND ASPL_COMPILE_FLAGS
  "-Wall"
  "-Wextra"
  "-Wno-invalid-offsetof"
  "-Wno-unused-parameter"
)

if(CMAKE_BUILD_TYPE STREQUAL "Debug")
  list(APPEND ASPL_COMPILE_FLAGS
    "-g" # Use -g instead of -ggdb for broader compatibility
    # "-funwind-tables" # Often default or not needed on macOS/Clang
    # "-fno-omit-frame-pointer" # Useful for debugging
  )
endif()

option(ASPL_ENABLE_SANITIZERS "Enable Clang sanitizers for libASPL" OFF)
if(ASPL_ENABLE_SANITIZERS AND CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  list(APPEND ASPL_COMPILE_FLAGS "-fsanitize=address")
  # Linker flags might need to be applied differently depending on static/shared
  # set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -fsanitize=address")
  # set(CMAKE_SHARED_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS} -fsanitize=address")
endif()

# --- Code Generation ---
set(OBJECT_LIST
  "Device"
  "MuteControl"
  "Object"
  "Plugin"
  "Stream"
  "VolumeControl"
)

# Define where generated sources will live in the build directory
set(GENERATED_SRC_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated_src")
file(MAKE_DIRECTORY ${GENERATED_SRC_DIR})

# Target for grouping code generation commands
add_custom_target(aspl_generate_sources)

set(GENERATED_SOURCES "") # List to hold paths to generated files

# Generate accessors
foreach(CLASS IN LISTS OBJECT_LIST)
  set(INPUT_JSON "${PROJECT_SOURCE_DIR}/src/${CLASS}.json")
  set(OUTPUT_CPP "${GENERATED_SRC_DIR}/${CLASS}.g.cpp")
  add_custom_command(
    OUTPUT ${OUTPUT_CPP} # Specify output file
    COMMAND ${PYTHON_EXECUTABLE} # Assumes python is found, or use find_package(PythonInterp)
      "${PROJECT_SOURCE_DIR}/scripts/generate-accessors.py"
        -i ${INPUT_JSON}
        -o ${OUTPUT_CPP}
    DEPENDS ${INPUT_JSON} # Re-run if JSON changes
            "${PROJECT_SOURCE_DIR}/scripts/generate-accessors.py"
    COMMENT "Generating ${CLASS}.g.cpp"
    VERBATIM
  )
  list(APPEND GENERATED_SOURCES ${OUTPUT_CPP})
endforeach()

# Generate bridge
set(BRIDGE_INPUT_JSON "${PROJECT_SOURCE_DIR}/src/Bridge.json")
set(BRIDGE_OUTPUT_CPP "${GENERATED_SRC_DIR}/Bridge.g.cpp")
add_custom_command(
  OUTPUT ${BRIDGE_OUTPUT_CPP}
  COMMAND ${PYTHON_EXECUTABLE}
    "${PROJECT_SOURCE_DIR}/scripts/generate-bridge.py"
    -i ${BRIDGE_INPUT_JSON}
    -o ${BRIDGE_OUTPUT_CPP}
  DEPENDS ${BRIDGE_INPUT_JSON}
          "${PROJECT_SOURCE_DIR}/scripts/generate-bridge.py"
  COMMENT "Generating Bridge.g.cpp"
  VERBATIM
)
list(APPEND GENERATED_SOURCES ${BRIDGE_OUTPUT_CPP})

# Generate strings
set(STRINGS_OUTPUT_CPP "${GENERATED_SRC_DIR}/Strings.g.cpp")

if(CMAKE_OSX_SYSROOT)
  set(ASPL_SYSROOT_PATH ${CMAKE_OSX_SYSROOT})
else()
  # Fallback if CMAKE_OSX_SYSROOT is empty (less reliable)
  execute_process(
    COMMAND xcrun --sdk macosx --show-sdk-path
    OUTPUT_VARIABLE ASPL_SYSROOT_PATH
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
  )
  if(NOT ASPL_SYSROOT_PATH)
     message(FATAL_ERROR "libASPL: Could not determine macOS SDK path (CMAKE_OSX_SYSROOT is empty and xcrun failed).")
  endif()
endif()
message(STATUS "libASPL: Using sysroot for generate-strings.py: ${ASPL_SYSROOT_PATH}")

add_custom_command(
  OUTPUT ${STRINGS_OUTPUT_CPP}
  COMMAND ${PYTHON_EXECUTABLE}
    "${PROJECT_SOURCE_DIR}/scripts/generate-strings.py"
    -c "${CMAKE_CXX_COMPILER}"
    -s "${ASPL_SYSROOT_PATH}" # <<< Use the determined path
    -o ${STRINGS_OUTPUT_CPP}
  DEPENDS "${PROJECT_SOURCE_DIR}/scripts/generate-strings.py"
  COMMENT "Generating Strings.g.cpp"
  VERBATIM
)
list(APPEND GENERATED_SOURCES ${STRINGS_OUTPUT_CPP})

# --- Library Target ---
# Collect original source files
set(ASPL_SOURCES
  "src/Client.cpp"
  "src/Convert.cpp"
  "src/Dispatcher.cpp"
  "src/Driver.cpp"
  "src/Storage.cpp"
  "src/Strings.cpp"
  "src/Tracer.cpp"
  "src/Uid.cpp"
  "src/VolumeCurve.cpp"
)
# Add original class sources
foreach(CLASS IN LISTS OBJECT_LIST)
  list(APPEND ASPL_SOURCES "src/${CLASS}.cpp")
endforeach()

# Add the library target, including generated sources
add_library(${LIB_TARGET} STATIC
  ${ASPL_SOURCES}
  ${GENERATED_SOURCES} # Add the list of generated files
)

# --- Add CORRECT dependency: library depends on code generation target ---
add_dependencies(${LIB_TARGET} aspl_generate_sources)
# ---

# Apply compile flags
target_compile_options(${LIB_TARGET} PRIVATE ${ASPL_COMPILE_FLAGS})

# Include directories
target_include_directories(${LIB_TARGET}
  PUBLIC
    $<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
  PRIVATE
    ${PROJECT_SOURCE_DIR}/src
    ${GENERATED_SRC_DIR}
)

# Link dependencies
find_library(LIB_CoreFoundation CoreFoundation REQUIRED)
target_link_libraries(${LIB_TARGET} PUBLIC ${LIB_CoreFoundation})

# Set output name and properties
set_target_properties(${LIB_TARGET} PROPERTIES
  OUTPUT_NAME ${LIB_NAME}
  VERSION ${PACKAGE_VERSION}
  # SOVERSION ${PACKAGE_VERSION_MAJOR} # If needed for shared libs
)
# set_property(TARGET ${LIB_TARGET} APPEND PROPERTY COMPATIBLE_INTERFACE_STRING ${PACKAGE_VERSION}) # Maybe not needed for static

# --- Installation ---
include(GNUInstallDirs) # Use standard install directory variables (CMAKE_INSTALL_LIBDIR etc.)

install(TARGETS ${LIB_TARGET}
  EXPORT ${PACKAGE_NAME}Targets
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
  RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR} # Likely not applicable for STATIC lib
  INCLUDES DESTINATION ${CMAKE_INSTALL_INCLUDEDIR} # Handled below by directory install
)

# Install public headers
install(DIRECTORY "${PROJECT_SOURCE_DIR}/include/" # Install the whole include dir
  DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
  FILES_MATCHING PATTERN "*.h" # Or specific headers
)

# --- CMake Package Config ---
install(EXPORT ${PACKAGE_NAME}Targets
  FILE ${PACKAGE_NAME}Targets.cmake
  NAMESPACE aspl::
  DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/${PACKAGE_NAME}"
)

include(CMakePackageConfigHelpers)

# Configure the package config file (e.g., libASPLConfig.cmake.in)
# Make sure you have a libASPLConfig.cmake.in file
configure_package_config_file(
  "${PROJECT_SOURCE_DIR}/${PACKAGE_NAME}Config.cmake.in" # Input template
  "${CMAKE_CURRENT_BINARY_DIR}/${PACKAGE_NAME}Config.cmake" # Output in build dir
  INSTALL_DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/${PACKAGE_NAME}"
  # PATH_VARS # Add paths to set if needed in the template
)

# Create the version file
write_basic_package_version_file(
  "${CMAKE_CURRENT_BINARY_DIR}/${PACKAGE_NAME}ConfigVersion.cmake"
  VERSION ${PACKAGE_VERSION}
  COMPATIBILITY SameMajorVersion # Allow compatible minor versions
)

# Install the config and version files
install(FILES
  "${CMAKE_CURRENT_BINARY_DIR}/${PACKAGE_NAME}Config.cmake"
  "${CMAKE_CURRENT_BINARY_DIR}/${PACKAGE_NAME}ConfigVersion.cmake"
  DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/${PACKAGE_NAME}"
)

# --- Testing (Optional, kept from original) ---
option(ASPL_BUILD_TESTS "Build libASPL tests" OFF) # Make testing optional
if(ASPL_BUILD_TESTS)
  enable_testing()
  find_package(GTest QUIET) # Use standard FindGTest
  if(NOT GTest_FOUND)
     message(STATUS "libASPL Tests: googletest not found via find_package, using FetchContent.")
     include(FetchContent)
     FetchContent_Declare(
         googletest
         GIT_REPOSITORY https://github.com/google/googletest.git
         GIT_TAG        release-1.12.1 # Or a specific commit/tag
     )
     FetchContent_MakeAvailable(googletest)
     # Manually add include directory if FetchContent doesn't handle it via target
     # list(APPEND TEST_INCLUDE_DIRS ${googletest_SOURCE_DIR}/googletest/include)
  else()
     message(STATUS "libASPL Tests: Found googletest via find_package.")
     # list(APPEND TEST_LINK_LIBS GTest::gtest GTest::gmock GTest::gtest_main) # Use imported targets
  endif()

  # Add test executable
  add_executable(${TEST_NAME}
    "test/Main.cpp"
    "test/TestClients.cpp"
    # ... other test files ...
    "test/TestStorage.cpp"
  )

  # Link test executable
  target_link_libraries(${TEST_NAME} PRIVATE
    ${LIB_TARGET}
    GTest::gtest # Link against imported targets if using find_package >= 3.14
    GTest::gtest_main
    # Or manually link if using FetchContent without imported targets:
    # ${CMAKE_CURRENT_BINARY_DIR}/googletest-build/lib/libgtest.a
    # ${CMAKE_CURRENT_BINARY_DIR}/googletest-build/lib/libgtest_main.a
  )

  # Include directories for tests
  target_include_directories(${TEST_NAME} PRIVATE
      ${PROJECT_SOURCE_DIR}/include
      ${PROJECT_SOURCE_DIR}/src
      ${GENERATED_SRC_DIR}
      ${googletest_SOURCE_DIR}/googletest/include # Include GTest headers
      ${googletest_SOURCE_DIR}/googlemock/include # Include GMock headers
  )

  # Add test to CTest
  include(GoogleTest)
  gtest_add_tests(TARGET ${TEST_NAME})

endif()

# --- Documentation (Optional) ---
option(ASPL_BUILD_DOCUMENTATION "Build Doxygen documentation for libASPL" OFF)
if(ASPL_BUILD_DOCUMENTATION)
  find_package(Doxygen)
  if(DOXYGEN_FOUND)
    # Configure Doxygen settings here or use a Doxyfile
    # ...
    add_custom_target(aspl_doxygen ALL
      # DEPENDS ${LIB_TARGET} # Optional: generate after build
      COMMAND ${DOXYGEN_EXECUTABLE} ${PROJECT_SOURCE_DIR}/Doxyfile # Assumes Doxyfile exists
      WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}
      COMMENT "Generating libASPL Doxygen documentation"
      VERBATIM
    )
  endif()
endif()

# --- Compile Commands Copy (Optional, use top-level setting if possible) ---
# The CMAKE_EXPORT_COMPILE_COMMANDS ON should handle this globally.
# This custom command might be redundant or cause issues if top-level is also doing it.
# Consider removing this section if the global setting works for your tooling.
# add_custom_command(
#   TARGET ${LIB_TARGET} POST_BUILD
#   COMMAND ${CMAKE_COMMAND} -E copy_if_different
#     "${CMAKE_BINARY_DIR}/compile_commands.json" # Source is build root
#     "${PROJECT_SOURCE_DIR}/compile_commands.json" # Destination
#   COMMENT "Copying compile_commands.json to libASPL source root (redundant?)"
#   VERBATIM
# )
# add_custom_target(aspl_compile_commands ALL DEPENDS ${LIB_TARGET})
