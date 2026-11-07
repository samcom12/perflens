#include "kernels.h"

#include <math.h>
#include <stddef.h>

/*
 * CASE-01: Vectorizable loop
 *
 * Each iteration is independent and performs a simple element-wise
 * operation. This should be a good compiler vectorization candidate.
 */
void vectorizable_kernel(const double *a, const double *b,
                         double *c, size_t n)
{
    for (size_t i = 0; i < n; ++i) {
        c[i] = a[i] + 2.0 * b[i];
    }
}

/*
 * CASE-02: Missed vectorization
 *
 * Each iteration depends on the previous iteration through a[i - 1].
 * This creates a loop-carried dependency.
 */
void missed_vectorization_kernel(double *a, size_t n)
{
    for (size_t i = 1; i < n; ++i) {
        a[i] = a[i - 1] * 1.000001 + 0.5;
    }
}

/*
 * CASE-03: Aliasing
 *
 * The compiler cannot assume that a, b and c point to completely
 * separate memory regions.
 */
void aliasing_kernel(const double *a, const double *b,
                     double *c, size_t n)
{
    for (size_t i = 0; i < n; ++i) {
        c[i] = a[i] + b[i];
    }
}

/*
 * CASE-04: Explicit dependency
 *
 * Another controlled loop-carried dependency case.
 */
void dependency_kernel(double *a, size_t n)
{
    for (size_t i = 1; i < n; ++i) {
        a[i] = a[i - 1] + 1.0;
    }
}

/*
 * CASE-05: Division inside loop
 *
 * The divisor is loop-invariant, making this a controlled target for
 * division-hoisting / strength-reduction analysis.
 */
void division_kernel(const double *a, double *b,
                     size_t n, double divisor)
{
    for (size_t i = 0; i < n; ++i) {
        b[i] = a[i] / divisor;
    }
}

/*
 * CASE-06: Expensive mathematical operation
 *
 * sqrt() is intentionally inside the loop so static analysis and
 * compiler feedback have a controlled math case to inspect.
 */
void expensive_math_kernel(const double *a, double *b,
                           size_t n)
{
    for (size_t i = 0; i < n; ++i) {
        b[i] = sqrt(a[i] * a[i] + 1.0);
    }
}
