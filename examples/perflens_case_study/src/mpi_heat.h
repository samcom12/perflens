#ifndef PERF_LENS_CASE_STUDY_MPI_HEAT_H
#define PERF_LENS_CASE_STUDY_MPI_HEAT_H

int mpi_case_initialize(int *argc, char ***argv);
int mpi_case_finalize(void);

int mpi_exchange_halo_blocking(double *send_buffer,
                               double *recv_buffer,
                               int count,
                               int rank,
                               int size);

int mpi_exchange_halo_nonblocking(double *send_buffer,
                                  double *recv_buffer,
                                  int count,
                                  int rank,
                                  int size);

#endif
