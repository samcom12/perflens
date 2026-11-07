program implicit_typing
    integer :: n, i
    real(8), allocatable :: values(:)

    n = 100
    allocate(values(n))

    do i = 1, n
        values(i) = i * 2.0d0
    end do

    print *, values(n)
end program implicit_typing
