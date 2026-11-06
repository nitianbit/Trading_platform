"""Build both images from one stable source fingerprint."""
import subprocess
from source_manifest import ROOT, source_fingerprint, verify_image


def main():
    expected=source_fingerprint()
    for tag, dockerfile in [("dhk-paper-backend:local","Dockerfile"),("dhk-paper-web:local","deploy/Dockerfile.web")]:
        subprocess.run(["docker","build","-f",dockerfile,"--build-arg","DHK_SOURCE_FINGERPRINT="+expected,"-t",tag,"."],cwd=ROOT,check=True)
        verify_image(tag,expected)
    if source_fingerprint()!=expected: raise RuntimeError("Source changed during build; rebuild from a stable working tree")
    print("Both images match the current source fingerprint: " + expected)


if __name__=="__main__": main()
