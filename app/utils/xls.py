import pandas as pd


def extract_queries_from_excel(path: str) -> list[str]:
    df = pd.read_excel(path, header=None)

    header_row = header_col = None

    for r in range(df.shape[0]):
        for c in range(df.shape[1]):
            cell = str(df.iat[r, c]).lower()
            if "наименование товара" in cell:
                header_row, header_col = r, c
                break
        if header_row is not None:
            break
    
    if header_row is None:
        raise ValueError("Не найден столбец 'Наименование товара'")
    
    queries = (
        df.iloc[header_row + 1 :, header_col]
        .dropna()
        .astype(str)
        .map(lambda x: x.split("(", 1)[0].strip())
        .drop_duplicates()
        .tolist()
    )

    queries = [q for q in queries if q]
    return queries