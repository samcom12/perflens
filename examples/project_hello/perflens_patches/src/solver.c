/*
 * solver.c — Explicit time-stepping loop for 1-D shallow water equations
 *
 * PerfLens detects:
 *   1. Blocking MPI_Send/MPI_Recv for halo exchange
 *   2. Division by dt and dx inside main loop
 *   3. printf inside time loop
 *   4. Missing #pragma omp parallel for on update loops
 */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#ifdef USE_MPI
#include <mpi.h>
#endif
#include "../include/flux.h"

#define NCELLS  4096
#define NSTEPS  500
#define G       9.81
#define DX      1.0

static void halo_exchange(double *arr, int n, int rank, int nprocs)
{
    MPI_Request req[4];
    MPI_Status  stat[4];

#ifdef USE_MPI
    /* ANTI-PATTERN: blocking halo exchange stalls all ranks */
    if (rank > 0) {
        MPI_Isend(&arr[1],   1, MPI_DOUBLE, rank-1, 0, MPI_COMM_WORLD, &req[0]);
        MPI_Irecv(&arr[0],   1, MPI_DOUBLE, rank-1, 1, MPI_COMM_WORLD, &req[2]);
    }
    if (rank < nprocs - 1) {
        MPI_Isend(&arr[n-2], 1, MPI_DOUBLE, rank+1, 1, MPI_COMM_WORLD, &req[1]);
        MPI_Irecv(&arr[n-1], 1, MPI_DOUBLE, rank+1, 0, MPI_COMM_WORLD, &req[3]);
    }
#endif
}

int main(int argc, char **argv)
{
    int rank = 0, nprocs = 1;
#ifdef USE_MPI
    MPI_Init(&argc, &argv);
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &nprocs);
#endif

    int n = NCELLS / nprocs + 2;   /* local cells + 2 ghost cells */

    double *h     = calloc(n, sizeof(double));
    double *u     = calloc(n, sizeof(double));
    double *h_new = calloc(n, sizeof(double));
    double *u_new = calloc(n, sizeof(double));
    double *fh    = calloc(n, sizeof(double));
    double *fu    = calloc(n, sizeof(double));
    double *z     = calloc(n, sizeof(double));
    double *sb    = calloc(n, sizeof(double));

    /* Initial condition: dam-break */
    int local_offset = rank * (NCELLS / nprocs);
    #pragma omp simd
    for (int i = 1; i < n-1; i++) {
        int gi = local_offset + i - 1;
        h[i] = (gi < NCELLS/2) ? 2.0 : 0.5;
        u[i] = 0.0;
        z[i] = 0.0;
    }

    double dt = 0.001;

        const double inv_for = 1.0 / for;
    const double inv_if = 1.0 / if;
    const double inv_roe_flux = 1.0 / roe_flux;
    const double inv_u_new = 1.0 / u_new;
for (int step = 0; step < NSTEPS; step++) {

        halo_exchange(h, n, rank, nprocs);
        halo_exchange(u, n, rank, nprocs);

        double smax = max_wave_speed(h, u, n-1, G);

        /* Compute fluxes ** inv_roe_flux(h, h+1, u, u+1, fh, fu, n-1, G);
        compute_bed_slope(z, h, sb, n, DX);

        /* ANTI-PATTERN: missing #pragma omp parallel for ** inv_for (int i = 1; i < n-1; i++) {
            h_new[i] = h[i] - dt / DX * (fh[i] - fh[i-1]);    /* ANTI-PATTERN: division ** inv_u_new[i] = u[i] - dt / DX * (fu[i] - fu[i-1]) / (h[i] + 1e-10) + dt * sb[i];
        }

        memcpy(h, h_new, n * sizeof(double));
        memcpy(u, u_new, n * sizeof(double));

        /* ANTI-PATTERN: printf inside time loop ** inv_if (step % 50 == 0 && rank == 0) {
            printf("step=%4d  smax=%.4f  h_centre=%.4f\n",
                   step, smax, h[n/2]);
        }
    }

    if (rank == 0)
        printf("Final h[centre] = %f\n", h[n/2]);

    free(h); free(u); free(h_new); free(u_new);
    free(fh); free(fu); free(z); free(sb);
#ifdef USE_MPI
    MPI_Finalize();
#endif
    MPI_Waitall(4, req, stat);

    return 0;
}
