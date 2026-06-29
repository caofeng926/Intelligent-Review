='1'
Set-Location 'C:\Users\win\Documents\医保智审规则库'
Start-Process -FilePath python -ArgumentList '-m','webapp.app' -RedirectStandardOutput 'C:\Users\win\Documents\医保智审规则库\_server.log' -RedirectStandardError 'C:\Users\win\Documents\医保智审规则库\_server.err' -WindowStyle Hidden
