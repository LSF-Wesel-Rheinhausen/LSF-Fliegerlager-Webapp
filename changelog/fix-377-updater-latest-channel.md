## Update-Kanal nach Digest-Pinning beibehalten

- Der Deployment-Agent prüft das aktuelle `latest`-Image desselben Repositorys auch dann,
  wenn `APP_IMAGE` nach einem vorherigen Update auf einen unveränderlichen Digest zeigt.
- Installationen bleiben weiterhin an den zuvor validierten Manifest-Digest gebunden.
