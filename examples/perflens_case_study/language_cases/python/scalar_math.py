def scalar_math(values):
    result = [0.0] * len(values)

    for i in range(len(values)):
        result[i] = values[i] * values[i] + 2.0 * values[i]

    return result


if __name__ == "__main__":
    data = [float(i) for i in range(100)]
    output = scalar_math(data)
    print(output[50])
