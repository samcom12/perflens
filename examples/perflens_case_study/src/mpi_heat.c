#include <mpi.h>
#include <stddef.h>
#include <stdio.h>

/*
 * MPI component for the case study.
 *
 * This file is intentionally small and isolates MPI communication patterns
 * so they can later be tested independently by PerfLens.
 */

int mpi_case_initialize(int *argc, char ***argv)
{
    return MPI_Init(argc, argv);
}

int mpi_case_finalize(void)
{
    return MPI_Finalize();
}

int mpi_exchange_halo_blocking(double *send_buffer,
                               double *recv_buffer,
                               int count,
                               int rank,
                               int size)
{
    if (size < 2) {
        return 0;
    }

    int left = (rank > 0) ? rank - 1 : MPI_PROC_NULL;
    int right = (rank < size - 1) ? rank + 1 : MPI_PROC_NULL;

    /*
     * Deliberate blocking communication case.
     * This is one of the PerfLens MPI optimization test targets.
     */
    MPI_Send(send_buffer, count, MPI_DOUBLE, left, 100, MPI_COMM_WORLD);
    MPI_Recv(recv_buffer, count, MPI_DOUBLE, right, 100,
            MPI_COMM_WORLD, MPI_STATUS_IGNORE);

    return 0;
}

int mpi_exchange_halo_nonblocking(double *send_buffer,
                                  double *recv_buffer,
                                  int count,
                                  int rank,
                                  int size)
{
    if (size < 2) {
        return 0;
    }

    int left = (rank > 0) ? rank - 1 : MPI_PROC_NULL;
    int right = (rank < size - 1) ? rank + 1 : MPI_PROC_NULL;

    MPI_Request requests[2];

    MPI_Irecv(recv_buffer, count, MPI_DOUBLE, right, 200,
              MPI_COMM_WORLD, &requests[0]);

    MPI_Isend(send_buffer, count, MPI_DOUBLE, left, 200,
              MPI_COMM_WORLD, &requests[1]);

    MPI_Waitall(2, requests, MPI_STATUSES_IGNORE);

    return 0;
}
