from __future__ import annotations
import argparse, json
from .service import GreenhouseService, demo
def main() -> None:
    parser=argparse.ArgumentParser(description="Greenhouse Climate Control")
    parser.add_argument("--demo",action="store_true"); parser.add_argument("--serve",action="store_true")
    parser.add_argument("--db",default="runtime.db"); parser.add_argument("--port",type=int,default=8080)
    args=parser.parse_args()
    if args.demo: demo(); return
    service=GreenhouseService(args.db)
    if args.serve:
        from .engine import serve
        server=serve(service,port=args.port)
        print(f"greenhouse listening on {args.port}")
        try: server.serve_forever()
        except KeyboardInterrupt: pass
        finally: server.server_close()
    else: print(json.dumps(service.health(),ensure_ascii=False,indent=2))
    service.close()
if __name__=="__main__": main()



