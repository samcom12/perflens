program saxpy_demo
  implicit none
  integer, parameter :: n = 1000
  real :: x(n), y(n), a
  integer :: i

  a = 2.0
  x = 1.0
  y = 0.0

  do i = 1, n
    y(i) = a * x(i) + y(i)
  end do

  print *, sum(y)
end program saxpy_demo

