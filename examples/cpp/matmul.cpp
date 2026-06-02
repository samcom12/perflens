/*
 * matmul.cpp — Dense matrix multiplication (no BLAS)
 *
 * Anti-patterns for PerfLens to detect:
 *   1. Naive i-j-k loop order (j-inner is cache-unfriendly for row-major)
 *   2. No loop tiling / blocking
 *   3. No SIMD or OpenMP parallelism
 *   4. std::vector<std::vector<double>> — indirect memory layout
 *   5. Scalar division inside loop for normalisation
 */

#include <cmath>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <chrono>
#include <vector>

using Matrix = std::vector<std::vector<double>>;

/* ANTI-PATTERN 1: indirect memory layout — each row is a separate allocation */
Matrix make_matrix(int n) {
    return Matrix(n, std::vector<double>(n, 0.0));
}

/* ANTI-PATTERN 2: naive i-j-k loop order — B accessed column-wise (cache miss) */
void matmul_naive(const Matrix &A, const Matrix &B, Matrix &C, int n) {
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            double sum = 0.0;
            for (int k = 0; k < n; k++) {
                sum += A[i][k] * B[k][j];   /* B[k][j] — stride-n access */
            }
            C[i][j] = sum;
        }
    }
}

/* ANTI-PATTERN 3: row normalisation with division in loop */
void row_normalize(Matrix &A, int n) {
    for (int i = 0; i < n; i++) {
        double row_norm = 0.0;
        for (int j = 0; j < n; j++)
            row_norm += A[i][j] * A[i][j];
        row_norm = std::sqrt(row_norm);

        /* ANTI-PATTERN 4: division inside loop — should precompute inv_norm */
        for (int j = 0; j < n; j++)
            A[i][j] /= row_norm;
    }
}

/* ANTI-PATTERN 5: Frobenius norm with transcendental inside the accumulation */
double frobenius_norm(const Matrix &A, int n) {
    double s = 0.0;
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++)
            s += std::pow(A[i][j], 2);   /* pow(x,2) instead of x*x */
    return std::sqrt(s);
}

int main(int argc, char **argv) {
    int n = (argc > 1) ? std::atoi(argv[1]) : 512;

    auto A = make_matrix(n);
    auto B = make_matrix(n);
    auto C = make_matrix(n);

    /* Initialise */
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++) {
            A[i][j] = static_cast<double>(i + j) / n;
            B[i][j] = static_cast<double>(i * j + 1) / (n * n);
        }

    auto t0 = std::chrono::high_resolution_clock::now();
    matmul_naive(A, B, C, n);
    auto t1 = std::chrono::high_resolution_clock::now();

    double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
    double gflops = (2.0 * n * n * n) / (ms * 1e6);

    std::printf("matmul_naive: n=%d  %.2f ms  %.2f GFLOP/s\n", n, ms, gflops);

    row_normalize(C, n);
    std::printf("Frobenius norm after normalise: %e\n", frobenius_norm(C, n));

    return 0;
}
