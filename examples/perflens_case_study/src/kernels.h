#ifndef PERF_LENS_CASE_STUDY_KERNELS_H
#define PERF_LENS_CASE_STUDY_KERNELS_H

#include <stddef.h>

void vectorizable_kernel(const double *a, const double *b,
                         double *c, size_t n);

void missed_vectorization_kernel(double *a, size_t n);

void aliasing_kernel(const double *a, const double *b,
                     double *c, size_t n);

void dependency_kernel(double *a, size_t n);

void division_kernel(const double *a, double *b,
                     size_t n, double divisor);

void expensive_math_kernel(const double *a, double *b,
                           size_t n);

#endif
