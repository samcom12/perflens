#include "heat.h"
#include "kernels.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static double wall_time_seconds(void)
{
    struct timespec ts;

    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return 0.0;
    }

    return (double)ts.tv_sec +
           (double)ts.tv_nsec * 1.0e-9;
}

static void print_usage(const char *program)
{
    fprintf(stderr,
            "Usage:\n"
            "  %s --mode serial [nx] [ny] [steps]\n"
            "  %s --mode openmp [nx] [ny] [steps]\n"
            "  %s --mode tiled [nx] [ny] [steps]\n"
            "  %s --mode kernel --kernel <name> [n]\n\n"
            "Kernel names:\n"
            "  vector\n"
            "  missed\n"
            "  alias\n"
            "  dependency\n"
            "  division\n"
            "  math\n",
            program, program, program, program);
}

static size_t parse_size(const char *text, const char *name)
{
    char *end = NULL;
    unsigned long value = strtoul(text, &end, 10);

    if (text[0] == '\0' || end == text || *end != '\0' || value < 2) {
        fprintf(stderr, "Invalid %s: %s\n", name, text);
        exit(EXIT_FAILURE);
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

static void run_kernel(const char *name, size_t n)
{
    double *a = malloc(n * sizeof(double));
    double *b = malloc(n * sizeof(double));
    double *c = malloc(n * sizeof(double));

    if (a == NULL || b == NULL || c == NULL) {
        fprintf(stderr, "Failed to allocate kernel buffers\n");
        free(a);
        free(b);
        free(c);
        exit(EXIT_FAILURE);
    }

    for (size_t i = 0; i < n; ++i) {
        a[i] = 1.0 + (double)i * 0.001;
        b[i] = 2.0 + (double)i * 0.002;
        c[i] = 0.0;
    }

    if (strcmp(name, "vector") == 0) {
        vectorizable_kernel(a, b, c, n);
    } else if (strcmp(name, "missed") == 0) {
        missed_vectorization_kernel(a, n);
    } else if (strcmp(name, "alias") == 0) {
        aliasing_kernel(a, b, c, n);
    } else if (strcmp(name, "dependency") == 0) {
        dependency_kernel(a, n);
    } else if (strcmp(name, "division") == 0) {
        division_kernel(a, c, n, 2.0);
    } else if (strcmp(name, "math") == 0) {
        expensive_math_kernel(a, c, n);
    } else {
        fprintf(stderr, "Unknown kernel: %s\n", name);
        free(a);
        free(b);
        free(c);
        exit(EXIT_FAILURE);
    }

    double checksum;

    /*
     * Some kernels modify 'a' directly rather than writing to 'c'.
     * Use the output buffer that was actually modified.
     */
    if (strcmp(name, "missed") == 0 ||
        strcmp(name, "dependency") == 0) {
        checksum = compute_checksum(a, 1, n);
    } else {
        checksum = compute_checksum(c, 1, n);
    }

    printf("Kernel: %s\n", name);
    printf("Elements: %zu\n", n);
    printf("Checksum: %.17g\n", checksum);

    free(a);
    free(b);
    free(c);
}

static int run_heat_mode(const char *mode,
                         size_t nx,
                         size_t ny,
                         size_t steps)
{
    const double alpha = 0.1;
    const double dt = 0.01;
    const double boundary_value = 0.0;

    const size_t elements = nx * ny;

    double *current = calloc(elements, sizeof(double));
    double *next = calloc(elements, sizeof(double));

    if (current == NULL || next == NULL) {
        fprintf(stderr,
                "Failed to allocate grid of %zu elements\n",
                elements);
        free(current);
        free(next);
        return EXIT_FAILURE;
    }

    heat_initialize(current, nx, ny);
    heat_apply_boundary(current, nx, ny, boundary_value);
    heat_apply_boundary(next, nx, ny, boundary_value);

    double start = wall_time_seconds();

    for (size_t step = 0; step < steps; ++step) {
        if (strcmp(mode, "serial") == 0) {
            heat_step(current, next, nx, ny, alpha, dt);
        } else if (strcmp(mode, "openmp") == 0) {
            heat_step_openmp(current, next, nx, ny, alpha, dt);
        } else if (strcmp(mode, "tiled") == 0) {
            heat_step_tiled(current, next, nx, ny, alpha, dt);
        } else {
            fprintf(stderr, "Unknown heat mode: %s\n", mode);
            free(current);
            free(next);
            return EXIT_FAILURE;
        }

        heat_apply_boundary(next, nx, ny, boundary_value);

        double *tmp = current;
        current = next;
        next = tmp;
    }

    double elapsed = wall_time_seconds() - start;
    double checksum = compute_checksum(current, nx, ny);

    printf("PerfLens Case Study: 2D Heat Diffusion\n");
    printf("Mode: %s\n", mode);
    printf("Grid: %zu x %zu\n", nx, ny);
    printf("Steps: %zu\n", steps);
    printf("Runtime: %.9f s\n", elapsed);
    printf("Checksum: %.17g\n", checksum);
    printf("Centre: %.17g\n",
           current[(nx / 2) * ny + (ny / 2)]);

    free(current);
    free(next);

    return EXIT_SUCCESS;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        print_usage(argv[0]);
        return EXIT_FAILURE;
    }

    if (strcmp(argv[1], "--mode") != 0) {
        print_usage(argv[0]);
        return EXIT_FAILURE;
    }

    const char *mode = argv[2];

    if (strcmp(mode, "kernel") == 0) {
        if (argc < 5 || strcmp(argv[3], "--kernel") != 0) {
            print_usage(argv[0]);
            return EXIT_FAILURE;
        }

        size_t n = (argc >= 6) ? parse_size(argv[5], "n") : 4096;

        run_kernel(argv[4], n);
        return EXIT_SUCCESS;
    }

    if (argc < 5 || argc > 6) {
        print_usage(argv[0]);
        return EXIT_FAILURE;
    }

    size_t nx = parse_size(argv[3], "nx");
    size_t ny = parse_size(argv[4], "ny");
    size_t steps = (argc == 6) ? parse_size(argv[5], "steps") : 100;

    return run_heat_mode(mode, nx, ny, steps);
}