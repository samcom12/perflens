def compute(values):
    result = [0.0] * len(values)

    for i in range(len(values)):
        result[i] = values[i] * values[i] + 1.0

    return result


if __name__ == "__main__":
    data = [float(i) for i in range(100)]
    output = compute(data)
    print(output[50])
