class DataValidator:


    @staticmethod
    def check_missing(df):

        missing = df.isnull().sum()

        if missing.sum() > 0:
            print("⚠ Missing data found")
            print(missing)

        else:
            print("✅ No missing data")


    @staticmethod
    def check_duplicates(df):

        duplicates = df.duplicated().sum()


        if duplicates > 0:
            print(
                f"⚠ {duplicates} duplicate candles found"
            )

        else:
            print("✅ No duplicate candles")