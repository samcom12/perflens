/*
 * stencil.c — 2D 5-point Laplacian stencil kernel
 *
 * Intentional anti-patterns for PerfLens case study:
 *   1. Triple-nested loop without tiling (cache unfriendly for large N)
 *   2. Division inside inner loop (should use reciprocal)
 *   3. Missing #pragma omp simd / parallel
 *   4. sqrt() called per-iteration when it could be hoisted
 *   5. printf inside timing loop
 */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <time.h>

#define N 1024
#define NITER 100

/* Allocate row-major 2D array */
static double **alloc2d(int rows, int cols) {
    double **a = (double **)malloc(rows * sizeof(double *));
    for (int i = 0; i < rows; i++)
        a[i] = (double *)malloc(cols * sizeof(double));
    return a;
}

static void free2d(double **a, int rows) {
    for (int i = 0; i < rows; i++) free(a[i]);
    free(a);
}

/* ANTI-PATTERN 1: no tiling, no simd pragma, cache-unfriendly for large N */
void stencil_naive(double **u, double **u_new, int n) {
    double inv_h2 = 1.0 / ((double)(n + 1) * (n + 1));  /* scaling factor */
    for (int i = 1; i < n - 1; i++) {
        for (int j = 1; j < n - 1; j++) {
            /* ANTI-PATTERN 2: division inside inner loop */
            double dx2 = (u[i+1][j] - 2.0 * u[i][j] + u[i-1][j]) / (1.0 / inv_h2);
            double dy2 = (u[i][j+1] - 2.0 * u[i][j] + u[i][j-1]) / (1.0 / inv_h2);
            /* ANTI-PATTERN 3: sqrt in inner loop (could be hoisted if norm is static) */
            double norm = sqrt(u[i][j] * u[i][j] + 1e-12);
            u_new[i][j] = u[i][j] + 0.25 * (dx2 + dy2) / norm;
        }
    }
}

/* ANTI-PATTERN 4: convergence check with printf inside iteration loop */
double compute_residual(double **u, double **u_new, int n) {
    double res = 0.0;
    for (int i = 1; i < n - 1; i++)
        for (int j = 1; j < n - 1; j++)
            res += (u_new[i][j] - u[i][j]) * (u_new[i][j] - u[i][j]);
    return sqrt(res);
}

int main(int argc, char **argv) {
    int n    = (argc > 1) ? atoi(argv[1]) : N;
    int iter = (argc > 2) ? atoi(argv[2]) : NITER;

    double **u     = alloc2d(n, n);
    double **u_new = alloc2d(n, n);

    /* Initialise: hot boundary at top */
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++) {
            u[i][j]     = (i == 0) ? 1.0 : 0.0;
            u_new[i][j] = u[i][j];
        }

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    for (int k = 0; k < iter; k++) {
        stencil_naive(u, u_new, n);

        /* ANTI-PATTERN 5: I/O inside iteration loop */
        if (k % 10 == 0) {
            double res = compute_residual(u, u_new, n);
            printf("iter %4d  residual = %e\n", k, res);
        }

        /* Swap pointers */
        double **tmp = u;
        u     = u_new;
        u_new = tmp;
    }

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double elapsed = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) * 1e-9;
    printf("Elapsed: %.3f s  (n=%d, iter=%d)\n", elapsed, n, iter);
    printf("Centre value: %e\n", u[n/2][n/2]);

    free2d(u, n);
    free2d(u_new, n);
    return 0;
}
