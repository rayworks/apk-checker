# apk-checker

The python scripts used to process the target APK/AAB file.


## Check the key information of an APK / AAB

A single script handles both file types and dispatches automatically based on
the input file extension (`.apk` via `aapt`, `.aab` via the bundled
`bundletool`). With no path argument it picks the first apk/aab found under the
current directory.

Usage:
* Install JDK 17 (required by the bundled `bundletool` jar, used for AAB files)

* Execute the command
```
python app-checker.py [full-path-to-apk-or-aab-file] [file-md5-to-check]
```

Sample Output (APK):
```
--------------------------------------------------------------------------------
package: name=your-app-pkgname, versionCode=**, versionName=**
application-label-en-GB:'app-name-en'
abiFilters : ["'arm64-v8a'"]
MinSDK : 30, TargetSDK : 37
Debuggable : False
App icon : ./cache/app-icon.png
Generated md5: e1a423555d9dc0905e129b784bdd75c1
--------------------------------------------------------------------------------
```

Sample Output (AAB):
```
--------------------------------------------------------------------------------
package: name=your-app-pkgname, versionCode=**, versionName=**
application-label: Your App Name (@string/app_name)
abiFilters : ['arm64-v8a', 'armeabi-v7a']
MinSDK : 29, TargetSDK : 35
Debuggable : False
App icon : ./cache/app-icon.png
Generated md5: f3835327600562e0320a4d2c8263aa25
--------------------------------------------------------------------------------
```

### App icon

The highest-density launcher icon is extracted to `./cache/app-icon.png` and, on
terminals that support inline images, rendered directly in the console:

* **kitty** — via the built-in `kitty +kitten icat`
* **iTerm2** — via the inline-image escape sequence
* otherwise it falls back to `chafa` / `viu` / `imgcat` / `catimg` if installed,
  or simply prints the saved path

WebP icons are normalised to PNG when [Pillow](https://pypi.org/project/pillow/)
is installed (`pip install pillow`). Adaptive (vector/XML) icons are skipped in
favour of the raster density variants.

## Install the app from an AAB

Usage:
* Install JDK 17

* Execute the command
```python
python bundle-installer.py -b AAB_FILE -ksf KEYSTORE -ksp KEYSTORE_PASS -alias ALIAS -kpass KEY_PASS
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