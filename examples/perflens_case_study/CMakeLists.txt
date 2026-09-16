cmake_minimum_required(VERSION 3.15)

project(perflens_case_study C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

option(ENABLE_OPENMP "Enable OpenMP support" ON)
option(ENABLE_MPI "Enable MPI support" OFF)

set(COMMON_SOURCES
    src/heat.c
    src/kernels.c
    src/io.c
)

# -------------------------
# Serial / OpenMP executable
# -------------------------
add_executable(heat_solver
    src/main.c
    ${COMMON_SOURCES}
)

target_include_directories(heat_solver PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_link_libraries(heat_solver PRIVATE m)

if(ENABLE_OPENMP)
    find_package(OpenMP)

    if(OpenMP_C_FOUND)
        target_link_libraries(heat_solver PRIVATE OpenMP::OpenMP_C)
        target_compile_definitions(heat_solver PRIVATE USE_OPENMP)
    else()
        message(WARNING "OpenMP requested but not found; building without OpenMP")
    endif()
endif()

# -------------------------
# MPI executable
# -------------------------
if(ENABLE_MPI)
    find_package(MPI REQUIRED)

    add_executable(heat_solver_mpi
        src/main_mpi.c
        src/heat.c
        src/kernels.c
        src/io.c
        src/mpi_heat.c
    )

    target_include_directories(heat_solver_mpi PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
    )

    target_link_libraries(heat_solver_mpi PRIVATE
        MPI::MPI_C
        m
    )

    if(OpenMP_C_FOUND)
        target_link_libraries(heat_solver_mpi PRIVATE OpenMP::OpenMP_C)
    endif()

    target_compile_definitions(heat_solver_mpi PRIVATE USE_MPI)
endif()
