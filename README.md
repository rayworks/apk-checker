# apk-checker

The python scripts used to process the target APK/AAR file.


## Check the key information of APK
Usage:

* Execute the command
```
python apk-checker.py [full-path-to-apk-file] [file-md5-to-check]
```

Sample Output:
```
--------------------------------------------------------------------------------
package: name=your-app-pkgname, versionCode=**, versionName=**
application-label-en-GB:'app-name-en'
Generated md5: e1a423555d9dc0905e129b784bdd75c1
--------------------------------------------------------------------------------
```

## Install the app from an AAR

Usage:
* Install JDK 17

* Execute the command
```python
python bundle-installer.py -b AAR_FILE -ksf KEYSTORE -ksp KEYSTORE_PASS -alias ALIAS -kpass KEY_PASS
```


## Credits
* [checkapk](https://github.com/viclee2014/checkapk)

* [Bundle tool](https://developer.android.google.cn/tools/bundletool)


License
-------

    Copyright 2017 rayworks

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.