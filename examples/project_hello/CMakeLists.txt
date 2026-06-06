cmake_minimum_required(VERSION 3.16)
project(swe_solver C)

set(CMAKE_C_STANDARD 11)

# Optional MPI support
find_package(MPI)
find_package(OpenMP)

set(SOURCES
    src/flux.c
    src/solver.c
    src/io.c
)

add_executable(swe_solver ${SOURCES})
target_include_directories(swe_solver PRIVATE include)
target_link_libraries(swe_solver m)

if(OpenMP_C_FOUND)
    target_link_libraries(swe_solver OpenMP::OpenMP_C)
endif()

if(MPI_C_FOUND)
    target_compile_definitions(swe_solver PRIVATE USE_MPI)
    target_link_libraries(swe_solver MPI::MPI_C)
endif()

# CTest for validation
enable_testing()
add_test(NAME run_solver COMMAND swe_solver)
