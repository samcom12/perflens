#ifndef PERF_LENS_CASE_STUDY_HEAT_H
#define PERF_LENS_CASE_STUDY_HEAT_H

#include <stddef.h>

void heat_initialize(double *grid, size_t nx, size_t ny);
void heat_step(const double *current, double *next,
               size_t nx, size_t ny, double alpha, double dt);

void heat_step_tiled(const double *current, double *next,
                     size_t nx, size_t ny, double alpha, double dt);

void heat_step_openmp(const double *current, double *next,
                      size_t nx, size_t ny, double alpha, double dt);

void heat_apply_boundary(double *grid, size_t nx, size_t ny,
                         double boundary_value);

double heat_compute_error(const double *a, const double *b,
                          size_t nx, size_t ny);

#endif
