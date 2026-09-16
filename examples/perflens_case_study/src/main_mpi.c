#include "heat.h"
#include "mpi_heat.h"

#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static double wall_time_seconds(void)
{
    return MPI_Wtime();
}

static size_t parse_size(const char *text, const char *name)
{
    char *end = NULL;
    unsigned long value = strtoul(text, &end, 10);

    if (text[0] == '\0' || end == text || *end != '\0' || value < 2) {
        fprintf(stderr, "Invalid %s: %s\n", name, text);
        MPI_Abort(MPI_COMM_WORLD, EXIT_FAILURE);
    }

    return (size_t)value;
}

static double compute_checksum(const double *grid,
                               size_t nx,
                               size_t ny)
{
    double sum = 0.0;

    for (size_t i = 0; i < nx; ++i) {
        for (size_t j = 0; j < ny; ++j) {
            sum += grid[i * ny + j];
        }
    }

    return sum;
}

int main(int argc, char **argv)
{
    mpi_case_initialize(&argc, &argv);

    int rank = 0;
    int size = 1;

    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);

    size_t nx = (argc >= 2) ? parse_size(argv[1], "nx") : 128;
    size_t ny = (argc >= 3) ? parse_size(argv[2], "ny") : 128;
    size_t steps = (argc >= 4) ? parse_size(argv[3], "steps") : 20;

    const size_t elements = nx * ny;

    double *current = calloc(elements, sizeof(double));
    double *next = calloc(elements, sizeof(double));
    double *send_buffer = calloc(ny, sizeof(double));
    double *recv_buffer = calloc(ny, sizeof(double));

    if (!current || !next || !send_buffer || !recv_buffer) {
        fprintf(stderr, "Rank %d: allocation failed\n", rank);
        free(current);
        free(next);
        free(send_buffer);
        free(recv_buffer);
        mpi_case_finalize();
        return EXIT_FAILURE;
    }

    heat_initialize(current, nx, ny);
    heat_apply_boundary(current, nx, ny, 0.0);
    heat_apply_boundary(next, nx, ny, 0.0);

    for (size_t j = 0; j < ny; ++j) {
        send_buffer[j] = current[j];
    }

    MPI_Barrier(MPI_COMM_WORLD);

    double start = wall_time_seconds();

    for (size_t step = 0; step < steps; ++step) {
        /*
         * Deliberate blocking communication case.
         */
        mpi_exchange_halo_blocking(
            send_buffer,
            recv_buffer,
            (int)ny,
            rank,
            size
        );

        heat_step(current, next, nx, ny, 0.1, 0.01);
        heat_apply_boundary(next, nx, ny, 0.0);

        double *tmp = current;
        current = next;
        next = tmp;
    }

    MPI_Barrier(MPI_COMM_WORLD);

    double elapsed = wall_time_seconds() - start;
    double local_checksum = compute_checksum(current, nx, ny);
    double global_checksum = 0.0;

    MPI_Reduce(
        &local_checksum,
        &global_checksum,
        1,
        MPI_DOUBLE,
        MPI_SUM,
        0,
        MPI_COMM_WORLD
    );

    if (rank == 0) {
        printf("PerfLens Case Study: MPI Heat Diffusion\n");
        printf("Ranks: %d\n", size);
        printf("Grid: %zu x %zu\n", nx, ny);
        printf("Steps: %zu\n", steps);
        printf("Runtime: %.9f s\n", elapsed);
        printf("Checksum: %.17g\n", global_checksum);
    }

    free(current);
    free(next);
    free(send_buffer);
    free(recv_buffer);

    mpi_case_finalize();

    return EXIT_SUCCESS;
}
