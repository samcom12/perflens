! jacobi.f90 — 2D Jacobi iterative solver
!
! Anti-patterns for PerfLens to detect and optimize:
!   1. Missing IMPLICIT NONE
!   2. Transcendentals (SIN/COS) inside innermost DO loop
!   3. Synchronous MPI_SEND/MPI_RECV (blocking halo exchange)
!   4. Division inside inner loop
!   5. No !$OMP PARALLEL or !$OMP SIMD directives
!   6. WRITE statement inside iteration loop

MODULE jacobi_utils
  IMPLICIT NONE
  INTEGER, PARAMETER :: dp = KIND(1.0D0)
CONTAINS

  ! ANTI-PATTERN 1: subroutine without IMPLICIT NONE in pre-module code
  SUBROUTINE init_field(u, nx, ny)
    INTEGER, INTENT(IN)  :: nx, ny
    REAL(dp), INTENT(OUT) :: u(nx, ny)
    INTEGER :: i, j
    DO j = 1, ny
      DO i = 1, nx
        u(i,j) = SIN(REAL(i,dp)*3.14159265d0/REAL(nx,dp)) * &
                 COS(REAL(j,dp)*3.14159265d0/REAL(ny,dp))
      END DO
    END DO
  END SUBROUTINE init_field

END MODULE jacobi_utils


PROGRAM jacobi_solver
  USE jacobi_utils
  USE mpi
  IMPLICIT NONE

  INTEGER, PARAMETER :: NX = 512, NY = 512, NITER = 200
  REAL(dp) :: u(NX, NY), u_new(NX, NY)
  REAL(dp) :: residual, global_res, inv_4
  INTEGER  :: i, j, k, ierr, rank, nprocs
  INTEGER  :: local_ny, j_start, j_end
  REAL(dp) :: t_start, t_end

  ! --- MPI init ---
  CALL MPI_INIT(ierr)
  CALL MPI_COMM_RANK(MPI_COMM_WORLD, rank, ierr)
  CALL MPI_COMM_SIZE(MPI_COMM_WORLD, nprocs, ierr)

  ! Decompose rows across ranks
  local_ny = NY / nprocs
  j_start  = rank * local_ny + 1
  j_end    = j_start + local_ny - 1

  ! Initialize field
  CALL init_field(u, NX, NY)
  u_new = u

  ! ANTI-PATTERN 2: inv_4 could be a parameter, but computed inside loop
  t_start = MPI_Wtime()

  DO k = 1, NITER

    ! ANTI-PATTERN 3: Division inside inner loop  (use inv_4 = 0.25_dp instead)
    DO j = j_start+1, j_end-1
      DO i = 2, NX-1
        u_new(i,j) = (u(i+1,j) + u(i-1,j) + u(i,j+1) + u(i,j-1)) / 4.0_dp
      END DO
    END DO

    ! ANTI-PATTERN 4: Blocking halo exchange — ranks stall waiting for neighbours
    IF (rank > 0) THEN
      CALL MPI_SEND(u_new(1, j_start), NX, MPI_DOUBLE_PRECISION, &
                    rank-1, 0, MPI_COMM_WORLD, ierr)
      CALL MPI_RECV(u(1, j_start-1), NX, MPI_DOUBLE_PRECISION, &
                    rank-1, 1, MPI_COMM_WORLD, MPI_STATUS_IGNORE, ierr)
    END IF
    IF (rank < nprocs-1) THEN
      CALL MPI_SEND(u_new(1, j_end), NX, MPI_DOUBLE_PRECISION, &
                    rank+1, 1, MPI_COMM_WORLD, ierr)
      CALL MPI_RECV(u(1, j_end+1), NX, MPI_DOUBLE_PRECISION, &
                    rank+1, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE, ierr)
    END IF

    ! Local residual
    residual = 0.0_dp
    DO j = j_start, j_end
      DO i = 1, NX
        residual = residual + (u_new(i,j) - u(i,j))**2
      END DO
    END DO

    ! Global reduction
    CALL MPI_ALLREDUCE(residual, global_res, 1, MPI_DOUBLE_PRECISION, &
                       MPI_SUM, MPI_COMM_WORLD, ierr)
    global_res = SQRT(global_res)

    u = u_new

    ! ANTI-PATTERN 5: I/O inside iteration loop
    IF (rank == 0 .AND. MOD(k, 20) == 0) THEN
      WRITE(*,'(A,I5,A,ES12.4)') 'iter ', k, '  res = ', global_res
    END IF

    IF (global_res < 1.0D-8) EXIT

  END DO

  t_end = MPI_Wtime()

  IF (rank == 0) THEN
    WRITE(*,'(A,F8.3,A)') 'Elapsed: ', t_end - t_start, ' s'
    WRITE(*,'(A,ES12.4)') 'Final residual: ', global_res
  END IF

  CALL MPI_FINALIZE(ierr)

END PROGRAM jacobi_solver
