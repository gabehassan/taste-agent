import sys
if __name__ == "__main__" and (len(sys.argv) > 1 and sys.argv[1] == "worker"):
    from .worker import main; main()
