from ibind import IbkrClient
from ibind.oauth.oauth1a import OAuth1aConfig

from ..settings import settings

# DU-changeme => Example paper account


def main():
    # Example only: build client from the first configured account
    if not settings.accounts:
        raise SystemExit("No accounts configured in broker.env")
    acc = settings.accounts[0]
    client = IbkrClient(use_oauth=True, oauth_config=OAuth1aConfig(**acc.get_broker_oauth_params()))

    portfolio_accounts = client.portfolio_accounts().data
    print("Portfolio Accounts:", portfolio_accounts)


if __name__ == "__main__":
    main()
