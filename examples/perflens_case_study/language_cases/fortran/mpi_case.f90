program mpi_case
    use mpi
    implicit none

    integer :: ierr, rank, size
    integer :: value, status(MPI_STATUS_SIZE)

    call MPI_Init(ierr)
    call MPI_Comm_rank(MPI_COMM_WORLD, rank, ierr)
    call MPI_Comm_size(MPI_COMM_WORLD, size, ierr)

    value = rank

    if (size >= 2) then
        if (rank == 0) then
            call MPI_Send(value, 1, MPI_INTEGER, 1, 0, MPI_COMM_WORLD, ierr)
        else if (rank == 1) then
            call MPI_Recv(value, 1, MPI_INTEGER, 0, 0, MPI_COMM_WORLD, status, ierr)
        end if
    end if

    call MPI_Finalize(ierr)
end program mpi_case
