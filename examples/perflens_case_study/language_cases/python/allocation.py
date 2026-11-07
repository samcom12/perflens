def build_values(n):
    result = []

    for i in range(n):
        result.append(i * 2.0)

    return result


if __name__ == "__main__":
    values = build_values(100)
    print(values[-1])
