#include "heat.h"

#include <math.h>
#include <stddef.h>

void heat_initialize(double *grid, size_t nx, size_t ny)
{
    for (size_t i = 0; i < nx; ++i) {
        for (size_t j = 0; j < ny; ++j) {
            double x = (double)i / (double)(nx - 1);
            double y = (double)j / (double)(ny - 1);

            grid[i * ny + j] = sin(x * 3.141592653589793) *
                               sin(y * 3.141592653589793);
        }
    }
}

void heat_step(const double *current, double *next,
               size_t nx, size_t ny, double alpha, double dt)
{
    const double diffusion_coeff = alpha * dt;

    for (size_t i = 1; i < nx - 1; ++i) {
        for (size_t j = 1; j < ny - 1; ++j) {
            size_t idx = i * ny + j;

            double laplacian =
                current[(i - 1) * ny + j] +
                current[(i + 1) * ny + j] +
                current[i * ny + (j - 1)] +
                current[i * ny + (j + 1)] -
                4.0 * current[idx];

            next[idx] = current[idx] + diffusion_coeff * laplacian;
        }
    }
}

void heat_step_tiled(const double *current, double *next,
                     size_t nx, size_t ny, double alpha, double dt)
{
    const double inv_dt = 1.0 / dt;

#ifndef TILE
#define TILE 16
#endif

    for (size_t ii = 1; ii < nx - 1; ii += TILE) {
        size_t i_end = (ii + TILE < nx - 1) ? ii + TILE : nx - 1;

        for (size_t jj = 1; jj < ny - 1; jj += TILE) {
            size_t j_end = (jj + TILE < ny - 1) ? jj + TILE : ny - 1;

            for (size_t i = ii; i < i_end; ++i) {
                for (size_t j = jj; j < j_end; ++j) {
                    size_t idx = i * ny + j;

                    double laplacian =
                        current[(i - 1) * ny + j] +
                        current[(i + 1) * ny + j] +
                        current[i * ny + (j - 1)] +
                        current[i * ny + (j + 1)] -
                        4.0 * current[idx];

                    next[idx] = current[idx] +
                                alpha * laplacian * inv_dt;
                }
            }
        }
    }
}

void heat_step_openmp(const double *current, double *next,
                      size_t nx, size_t ny, double alpha, double dt)
{
    const double inv_dt = 1.0 / dt;

    #pragma omp parallel for schedule(static)
    for (size_t i = 1; i < nx - 1; ++i) {
        for (size_t j = 1; j < ny - 1; ++j) {
            size_t idx = i * ny + j;

            double laplacian =
                current[(i - 1) * ny + j] +
                current[(i + 1) * ny + j] +
                current[i * ny + (j - 1)] +
                current[i * ny + (j + 1)] -
                4.0 * current[idx];

            next[idx] = current[idx] + alpha * laplacian * inv_dt;
        }
    }
}

void heat_apply_boundary(double *grid, size_t nx, size_t ny,
                         double boundary_value)
{
    for (size_t i = 0; i < nx; ++i) {
        grid[i * ny] = boundary_value;
        grid[i * ny + (ny - 1)] = boundary_value;
    }

    for (size_t j = 0; j < ny; ++j) {
        grid[j] = boundary_value;
        grid[(nx - 1) * ny + j] = boundary_value;
    }
}

double heat_compute_error(const double *a, const double *b,
                          size_t nx, size_t ny)
{
    double max_error = 0.0;

    for (size_t i = 0; i < nx; ++i) {
        for (size_t j = 0; j < ny; ++j) {
            size_t idx = i * ny + j;
            double error = fabs(a[idx] - b[idx]);

            if (error > max_error) {
                max_error = error;
            }
        }
    }

    return max_error;
}
