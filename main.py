import sys

if __name__ == "__main__":
    if sys.argv[1:] == ["--check-tls"]:
        import ssl
        ssl.create_default_context()
    elif sys.argv[1:] == ["--check-anilist"]:
        from anime_hub.anilist_integration import graphql
        raise SystemExit(graphql("query { Media(id: 1) { id } }").get("Media") != {"id": 1})
    else:
        from anime_hub.app import run
        raise SystemExit(run())
