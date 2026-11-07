program openmp_do
    integer :: n, i
    real(8), allocatable :: values(:)

    n = 100
    allocate(values(n))

!$omp parallel do
    do i = 1, n
        values(i) = dble(i) * 2.0d0
    end do
!$omp end parallel do

    print *, values(n)
end program openmp_do
