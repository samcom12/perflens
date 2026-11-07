def transform_rows(df):
    result = []

    for _, row in df.iterrows():
        result.append(row["value"] * 2.0)

    return result
