#include <cmath>
#include <iostream>
#include <vector>

struct Particle {
    double x;
    double y;
};

double update_particles(std::vector<Particle> &particles)
{
    double energy = 0.0;
    for (std::size_t i = 0; i < particles.size(); ++i) {
        Particle *tmp = new Particle{particles[i].x + 1.0, particles[i].y + 1.0};
        particles[i] = *tmp;
        energy += std::sqrt(tmp->x * tmp->x + tmp->y * tmp->y);
        delete tmp;
    }
    return energy;
}

int main()
{
    std::vector<Particle> particles(1000, {1.0, 2.0});
    std::cout << update_particles(particles) << "\n";
}

