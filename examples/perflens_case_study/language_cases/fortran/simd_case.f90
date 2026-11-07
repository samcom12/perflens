program simd_case
    integer :: n, i
    real(8), allocatable :: a(:), b(:), c(:)

    n = 100
    allocate(a(n), b(n), c(n))

    do i = 1, n
        a(i) = dble(i)
        b(i) = dble(i) * 2.0d0
        c(i) = a(i) + b(i)
    end do

    print *, c(n)
end program simd_case
