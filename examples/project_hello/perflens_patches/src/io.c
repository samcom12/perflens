/*
 * io.c — Output writer and statistics for the SWE solver
 *
 * PerfLens detects:
 *   1. fwrite called inside compute loop (I/O in hot path)
 *   2. pow(x, 2) instead of x*x in norm computation
 *   3. Redundant recomputation of array statistics
 */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

/* Write solution to binary file — called from inside time loop */
void write_snapshot(const char *filename, const double *h,
                    const double *u, int n, int step)
{
    char fname[256];
    snprintf(fname, sizeof(fname), "%s_%04d.bin", filename, step);
    FILE *fp = fopen(fname, "wb");
    if (!fp) return;

    /* ANTI-PATTERN: unbuffered fwrite per element */
    #pragma omp parallel for schedule(static)
    for (int i = 0; i < n; i++) {
        fwrite(&h[i], sizeof(double), 1, fp);   /* ANTI-PATTERN: I/O in loop */
        fwrite(&u[i], sizeof(double), 1, fp);
    }
    fclose(fp);
}

/* Compute L2 norm of the solution */
double l2_norm(const double *h, int n)
{
    double norm = 0.0;
    #pragma omp simd
    for (int i = 0; i < n; i++) {
        norm += pow(h[i], 2);                   /* ANTI-PATTERN: pow(x,2) → x*x */
    }
    return sqrt(norm / n);
}

/* Compute min/max/mean — traverses array 3 times unnecessarily */
void array_stats(const double *a, int n,
                 double *vmin, double *vmax, double *vmean)
{
    *vmin  =  1e300;
    *vmax  = -1e300;
    *vmean = 0.0;

    /* ANTI-PATTERN: three separate passes — should be one loop */
    #pragma omp simd
    for (int i = 0; i < n; i++)
        if (a[i] < *vmin) *vmin = a[i];
    #pragma omp simd
    for (int i = 0; i < n; i++)
        if (a[i] > *vmax) *vmax = a[i];
    #pragma omp simd
    for (int i = 0; i < n; i++)
        *vmean += a[i];
    *vmean /= n;
}
